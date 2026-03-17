"""
core/memory.py
==============
Two-tier memory system for AgentForge.

Tier 1 — Short-term (SharedMemory)
    Fast key-value store backed by either an in-process dict or diskcache.
    Used for passing structured data between agents within a single run.

Tier 2 — Long-term vector memory (VectorMemory)
    FAISS index over sentence-transformer embeddings.
    Provides retrieval-augmented generation (RAG): agents can store free-text
    outputs and later retrieve the most semantically relevant chunks as
    additional context for their prompts.

Both tiers are exposed through MemoryManager, the single object injected
into every agent via BaseAgent.attach().
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ===========================================================================
# Tier 1 — Short-term key/value memory
# ===========================================================================

class BaseKVMemory(ABC):
    """Abstract interface for the key-value memory backend."""

    @abstractmethod
    def store(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    @abstractmethod
    def retrieve(self, key: str) -> Any | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def keys(self) -> list[str]: ...


class InMemoryBackend(BaseKVMemory):
    """Volatile in-process dict — fast, lost on restart."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl else None
        self._store[key] = (value, expires_at)

    def retrieve(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at and time.time() > expires_at:
            self.delete(key)
            return None
        return value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def keys(self) -> list[str]:
        return list(self._store.keys())


class DiskCacheBackend(BaseKVMemory):
    """Persistent disk-backed KV store via diskcache."""

    def __init__(self, directory: str = ".cache/memory") -> None:
        try:
            import diskcache  # type: ignore
            self._cache = diskcache.Cache(directory)
        except ImportError as exc:
            raise RuntimeError("pip install diskcache") from exc
        logger.info("memory.kv.diskcache_ready", directory=directory)

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._cache.set(key, value, expire=ttl)

    def retrieve(self, key: str) -> Any | None:
        return self._cache.get(key)

    def delete(self, key: str) -> None:
        self._cache.delete(key)

    def clear(self) -> None:
        self._cache.clear()

    def keys(self) -> list[str]:
        return list(self._cache.iterkeys())


class SharedMemory:
    """
    High-level facade over the short-term KV backend.

    Agents use namespaced keys (``{agent}:{key}``) via BaseAgent.remember()
    and BaseAgent.recall().  Direct access via store/retrieve is also fine
    for orchestrator-level metadata.

    Example::

        mem = SharedMemory()
        mem.store("run:objective", "Build a SaaS CRM")
        mem.append_to_list("run:events", {"ts": ..., "event": "step_started"})
        data = mem.retrieve("run:objective")
    """

    def __init__(self, backend: BaseKVMemory | None = None) -> None:
        from config import settings

        if backend is not None:
            self._backend = backend
        elif settings.memory_backend == "diskcache":
            self._backend = DiskCacheBackend(settings.memory_dir)
        else:
            self._backend = InMemoryBackend()
        logger.info("memory.kv.ready", backend=type(self._backend).__name__)

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Persist *value* under *key* with optional TTL (seconds)."""
        self._backend.store(key, value, ttl)
        logger.debug("memory.kv.store", key=key)

    def retrieve(self, key: str) -> Any | None:
        """Fetch the value stored at *key*; None if missing or expired."""
        return self._backend.retrieve(key)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def clear(self) -> None:
        self._backend.clear()

    def keys(self) -> list[str]:
        return self._backend.keys()

    def append_to_list(self, key: str, item: Any) -> None:
        """Append *item* to the list stored at *key* (creates list if absent)."""
        existing: list = self._backend.retrieve(key) or []
        existing.append(item)
        self._backend.store(key, existing)

    def dump(self) -> dict[str, Any]:
        """Return a full snapshot of current memory contents."""
        return {k: self._backend.retrieve(k) for k in self.keys()}


# ===========================================================================
# Tier 2 — Long-term vector memory (FAISS + RAG)
# ===========================================================================

@dataclass
class MemoryChunk:
    """
    A single retrievable unit stored in the vector index.

    Attributes:
        id:        Unique deterministic hash of the text content.
        text:      The raw text that was embedded and stored.
        source:    Who produced this chunk (agent name, tool name, etc.).
        metadata:  Arbitrary annotations (run_id, timestamp, topic, …).
        score:     Cosine similarity score populated during retrieval (0–1).
    """

    id: str
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    @classmethod
    def from_text(cls, text: str, source: str, **metadata: Any) -> "MemoryChunk":
        chunk_id = hashlib.sha256(f"{source}:{text}".encode()).hexdigest()[:16]
        return cls(id=chunk_id, text=text, source=source, metadata=metadata)

    def __str__(self) -> str:
        return f"[{self.score:.3f}] ({self.source}) {self.text[:120]}"


class VectorMemory:
    """
    Long-term semantic memory backed by FAISS and sentence-transformers.

    Provides retrieval-augmented generation (RAG):
    - store()    — embed and index a text chunk
    - retrieve() — find the *k* most semantically similar chunks
    - persist()  — save the FAISS index to disk
    - load()     — restore a previously saved index

    The index is kept in RAM during a run and optionally persisted to
    ``vector_memory_dir`` so context survives across sessions.

    If sentence-transformers or faiss-cpu are not installed, all operations
    degrade gracefully to no-ops with a warning — the system still runs,
    just without RAG enrichment.

    Example::

        vm = VectorMemory()
        vm.store("The TAM for B2B SaaS CRM is $50B globally.", source="research")
        chunks = vm.retrieve("market size CRM", k=3)
        for chunk in chunks:
            print(chunk)
    """

    def __init__(self, persist_dir: str | None = None, embedding_model: str | None = None) -> None:
        from config import settings

        self._persist_dir = Path(persist_dir or settings.vector_memory_dir)
        self._model_name = embedding_model or settings.embedding_model
        self._chunk_size = settings.rag_chunk_size
        self._chunk_overlap = settings.rag_chunk_overlap

        self._index: Any = None          # faiss.IndexFlatIP
        self._chunks: list[MemoryChunk] = []
        self._model: Any = None          # SentenceTransformer
        self._dim: int = 0
        self._available = False

        self._try_init()

    def _try_init(self) -> None:
        """Attempt to initialise FAISS + sentence-transformers; degrade gracefully."""
        try:
            import faiss  # type: ignore  # noqa: F401
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self._model_name)
            # Warm-up: embed a dummy string to get embedding dimension
            sample = self._model.encode(["ping"], normalize_embeddings=True)
            self._dim = sample.shape[1]

            import faiss
            self._index = faiss.IndexFlatIP(self._dim)   # inner-product ≡ cosine on normalised vecs
            self._available = True
            logger.info(
                "memory.vector.ready",
                model=self._model_name,
                dim=self._dim,
            )
        except ImportError as exc:
            logger.warning(
                "memory.vector.unavailable",
                reason=str(exc),
                hint="pip install faiss-cpu sentence-transformers",
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when FAISS and sentence-transformers are installed and ready."""
        return self._available

    def store(self, text: str, source: str, **metadata: Any) -> list[MemoryChunk]:
        """
        Chunk, embed, and index *text*.

        Long texts are split into overlapping windows of ``rag_chunk_size``
        characters so no single chunk exceeds the embedding model's context.

        Args:
            text:     Free-text content to index (agent output, search result, …).
            source:   Identifier of who produced this text (e.g. ``"research"``).
            **metadata: Arbitrary key-value annotations stored alongside the chunk.

        Returns:
            List of MemoryChunk objects that were added to the index.
            Returns an empty list when the vector layer is unavailable.
        """
        if not self._available:
            return []

        chunks = self._chunk_text(text, source, **metadata)
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        embeddings = self._embed(texts)

        self._index.add(embeddings)  # type: ignore[union-attr]
        self._chunks.extend(chunks)

        logger.debug(
            "memory.vector.stored",
            source=source,
            chunks=len(chunks),
            total_indexed=len(self._chunks),
        )
        return chunks

    def retrieve(self, query: str, k: int | None = None) -> list[MemoryChunk]:
        """
        Return the *k* most semantically similar chunks to *query*.

        Args:
            query: Natural-language query string.
            k:     Number of results (defaults to settings.rag_top_k).

        Returns:
            List of MemoryChunk objects sorted by descending similarity score.
            Returns an empty list when the index is empty or unavailable.
        """
        if not self._available or self._index.ntotal == 0:  # type: ignore[union-attr]
            return []

        from config import settings
        effective_k = min(k or settings.rag_top_k, self._index.ntotal)  # type: ignore[union-attr]

        query_vec = self._embed([query])
        scores, indices = self._index.search(query_vec, effective_k)  # type: ignore[union-attr]

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            chunk = self._chunks[idx]
            import dataclasses
            results.append(dataclasses.replace(chunk, score=float(score)))

        logger.debug(
            "memory.vector.retrieve",
            query=query[:60],
            k=effective_k,
            results=len(results),
        )
        return results

    def retrieve_as_context(self, query: str, k: int | None = None) -> str:
        """
        Retrieve relevant chunks and format them as a Markdown context block
        ready for injection into a Claude prompt.

        Returns an empty string when no relevant chunks are found.
        """
        chunks = self.retrieve(query, k=k)
        if not chunks:
            return ""
        lines = ["## Retrieved Memory Context (RAG)\n"]
        for i, chunk in enumerate(chunks, 1):
            lines.append(
                f"### Memory {i} — source: {chunk.source} (relevance: {chunk.score:.2f})\n"
                f"{chunk.text}\n"
            )
        return "\n".join(lines)

    def persist(self) -> Path:
        """
        Save the FAISS index and chunk metadata to disk.

        Returns:
            Path to the directory where files were written.

        Raises:
            RuntimeError: If the vector layer is unavailable.
        """
        if not self._available:
            raise RuntimeError("Vector memory is not available — cannot persist.")

        import faiss  # type: ignore

        self._persist_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._persist_dir / "index.faiss"
        meta_path = self._persist_dir / "chunks.json"

        faiss.write_index(self._index, str(index_path))
        meta = [
            {
                "id": c.id,
                "text": c.text,
                "source": c.source,
                "metadata": c.metadata,
            }
            for c in self._chunks
        ]
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        logger.info(
            "memory.vector.persisted",
            path=str(self._persist_dir),
            chunks=len(self._chunks),
        )
        return self._persist_dir

    def load(self) -> bool:
        """
        Restore a previously persisted FAISS index from disk.

        Returns:
            True if the index was successfully loaded, False otherwise.
        """
        if not self._available:
            return False

        import faiss  # type: ignore

        index_path = self._persist_dir / "index.faiss"
        meta_path = self._persist_dir / "chunks.json"

        if not index_path.exists() or not meta_path.exists():
            logger.debug("memory.vector.no_persisted_index")
            return False

        try:
            self._index = faiss.read_index(str(index_path))
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            self._chunks = [
                MemoryChunk(
                    id=r["id"],
                    text=r["text"],
                    source=r["source"],
                    metadata=r.get("metadata", {}),
                )
                for r in raw
            ]
            logger.info(
                "memory.vector.loaded",
                path=str(self._persist_dir),
                chunks=len(self._chunks),
            )
            return True
        except Exception:
            logger.exception("memory.vector.load_error")
            return False

    def clear(self) -> None:
        """Reset the in-memory index (does not delete persisted files)."""
        if self._available:
            import faiss  # type: ignore
            self._index = faiss.IndexFlatIP(self._dim)
        self._chunks.clear()
        logger.debug("memory.vector.cleared")

    @property
    def size(self) -> int:
        """Number of chunks currently in the index."""
        return len(self._chunks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]):  # -> np.ndarray
        """Embed a list of strings, returning L2-normalised float32 vectors."""
        import numpy as np  # type: ignore
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(vecs, dtype="float32")

    def _chunk_text(self, text: str, source: str, **metadata: Any) -> list[MemoryChunk]:
        """Split *text* into overlapping character windows."""
        size = self._chunk_size
        overlap = self._chunk_overlap
        chunks: list[MemoryChunk] = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            fragment = text[start:end].strip()
            if fragment:
                chunks.append(MemoryChunk.from_text(fragment, source, **metadata))
            if end == len(text):
                break
            start += size - overlap
        return chunks

    def __repr__(self) -> str:
        return (
            f"<VectorMemory available={self._available} "
            f"model={self._model_name!r} "
            f"chunks={self.size}>"
        )


# ===========================================================================
# Unified MemoryManager
# ===========================================================================

class MemoryManager:
    """
    Single object injected into every agent, combining both memory tiers.

    Agents interact with this class exclusively — they never instantiate
    SharedMemory or VectorMemory directly.

    Short-term usage::

        mgr.store("run:objective", "Build a SaaS CRM")
        obj = mgr.retrieve("run:objective")

    Long-term / RAG usage::

        mgr.index("The global CRM market is worth $50B.", source="research")
        context = mgr.rag_context("market size CRM software")
        # Inject context string into agent's Claude prompt

    Example::

        mgr = MemoryManager()
        mgr.store("ceo:vision", "Become the #1 AI-native CRM")
        mgr.index(ceo_output, source="ceo", run_id="abc123")
        relevant = mgr.rag_context("product vision and positioning")
    """

    def __init__(
        self,
        kv: SharedMemory | None = None,
        vector: VectorMemory | None = None,
    ) -> None:
        from config import settings

        self.kv = kv or SharedMemory()
        self.vector = vector if vector is not None else (
            VectorMemory() if settings.enable_vector_memory else None
        )
        logger.info(
            "memory.manager.ready",
            kv_backend=type(self.kv._backend).__name__,
            vector_available=self.vector.available if self.vector else False,
        )

    # ------------------------------------------------------------------
    # KV pass-through
    # ------------------------------------------------------------------

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in short-term memory."""
        self.kv.store(key, value, ttl)

    def retrieve(self, key: str) -> Any | None:
        """Retrieve a value from short-term memory."""
        return self.kv.retrieve(key)

    def delete(self, key: str) -> None:
        self.kv.delete(key)

    def append_to_list(self, key: str, item: Any) -> None:
        self.kv.append_to_list(key, item)

    def dump_kv(self) -> dict[str, Any]:
        return self.kv.dump()

    # ------------------------------------------------------------------
    # Vector / RAG pass-through
    # ------------------------------------------------------------------

    def index(self, text: str, source: str, **metadata: Any) -> list[MemoryChunk]:
        """
        Embed and index *text* in the long-term vector store.

        Silently does nothing if the vector layer is unavailable.

        Args:
            text:      Free-text to store (agent output, search result, …).
            source:    Producer identifier (agent name, tool name, …).
            **metadata: Arbitrary annotations attached to every chunk.

        Returns:
            List of stored MemoryChunk objects (empty if unavailable).
        """
        if self.vector is None or not self.vector.available:
            return []
        return self.vector.store(text, source, **metadata)

    def rag_context(self, query: str, k: int | None = None) -> str:
        """
        Retrieve the most relevant memory chunks for *query* and return
        them as a formatted Markdown string ready for prompt injection.

        Returns an empty string when vector memory is unavailable or empty.
        """
        if self.vector is None or not self.vector.available:
            return ""
        return self.vector.retrieve_as_context(query, k=k)

    def persist_vector(self) -> None:
        """Flush the vector index to disk (no-op if unavailable)."""
        if self.vector and self.vector.available:
            self.vector.persist()

    def load_vector(self) -> bool:
        """Restore vector index from disk. Returns True on success."""
        if self.vector and self.vector.available:
            return self.vector.load()
        return False

    def clear_all(self) -> None:
        """Reset both tiers (use between test runs)."""
        self.kv.clear()
        if self.vector:
            self.vector.clear()

    def __repr__(self) -> str:
        vec_size = self.vector.size if self.vector else 0
        return (
            f"<MemoryManager "
            f"kv_keys={len(self.kv.keys())} "
            f"vector_chunks={vec_size}>"
        )
