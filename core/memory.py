"""
core/memory.py
==============
Two-tier memory system for AgentForge.

Tier 1 — Short-term (SharedMemory)
    Fast key-value store backed by either an in-process dict or diskcache.
    Used for passing structured data between agents within a single run.

Tier 2 — Long-term vector memory (VectorMemory)
    FAISS index over Claude-generated embeddings.

    Embedding strategy
    ------------------
    Anthropic does not expose a dedicated embeddings endpoint, so we use a
    structured Claude prompt to produce a fixed-length (256-dim) float32
    embedding vector for any given text.  The prompt instructs the model to
    output a JSON array of 256 floats that encodes the semantic content of
    the input.  Vectors are L2-normalised before insertion so inner-product
    search is equivalent to cosine similarity.

    Trade-offs vs sentence-transformers
    - ✅ No extra dependencies or downloaded model weights (~500 MB saved)
    - ✅ Single API key for the entire system
    - ⚠  Slower (one API call per chunk vs local inference)
    - ⚠  Costs tokens; batching is essential

    Batching & caching
    ------------------
    _embed() processes texts in batches of EMBED_BATCH_SIZE and caches
    results in a local dict keyed by SHA-256(text) so repeated embeddings
    of identical strings never hit the API twice.

Both tiers are exposed through MemoryManager — the single object injected
into every agent via BaseAgent.attach().
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

EMBED_DIM = 256          # dimensionality of Claude-generated embeddings
EMBED_BATCH_SIZE = 8     # texts per embedding API call
EMBED_MAX_CHARS = 1500   # truncate each text to this before embedding


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
    and BaseAgent.recall(). Direct access is also fine for orchestrator-level
    metadata.

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
# Claude embedding engine
# ===========================================================================

class ClaudeEmbedder:
    """
    Produces fixed-length (EMBED_DIM) float32 embedding vectors using Claude.

    The model is prompted to return a JSON array of ``EMBED_DIM`` floats that
    semantically encodes the input text.  Outputs are L2-normalised so that
    FAISS inner-product search is equivalent to cosine similarity.

    Results are cached in ``_cache`` (SHA-256 → list[float]) so repeated
    embeddings of the same text never hit the API twice within a session.

    This class is internal to VectorMemory — agents never use it directly.
    """

    _SYSTEM = (
        f"You are a text embedding engine. "
        f"When given a text, respond ONLY with a JSON array of exactly {EMBED_DIM} "
        f"floating-point numbers between -1 and 1 that semantically encode the input. "
        f"Output nothing else — no explanation, no markdown, no code fences. "
        f"The array must have exactly {EMBED_DIM} elements."
    )

    def __init__(self, client: Any, model: str) -> None:
        self._client = client      # anthropic.Anthropic instance
        self._model = model
        self._cache: dict[str, list[float]] = {}

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts, returning one float32 vector per text.
        Results are served from cache when available.

        Args:
            texts: Strings to embed (truncated to EMBED_MAX_CHARS each).

        Returns:
            List of EMBED_DIM-length float lists, in the same order as *texts*.
        """
        results: list[list[float] | None] = [None] * len(texts)
        to_fetch: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            truncated = text[:EMBED_MAX_CHARS]
            key = hashlib.sha256(truncated.encode()).hexdigest()
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                to_fetch.append((i, truncated))

        # Batch API calls — one call per EMBED_BATCH_SIZE uncached texts
        for batch_start in range(0, len(to_fetch), EMBED_BATCH_SIZE):
            batch = to_fetch[batch_start: batch_start + EMBED_BATCH_SIZE]
            for idx, text in batch:
                vec = self._embed_single(text)
                key = hashlib.sha256(text.encode()).hexdigest()
                self._cache[key] = vec
                results[idx] = vec

        return [r for r in results if r is not None]

    def _embed_single(self, text: str) -> list[float]:
        """Call Claude to produce one embedding vector, with parse fallback."""
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                temperature=0.0,
                system=self._SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            raw = response.content[0].text.strip()
            vec = json.loads(raw)
            if not isinstance(vec, list) or len(vec) != EMBED_DIM:
                raise ValueError(f"Expected list of {EMBED_DIM}, got {type(vec)} len={len(vec)}")
            return [float(x) for x in vec]
        except Exception as exc:
            logger.warning("embedder.parse_error", error=str(exc), text_preview=text[:60])
            return self._fallback_vector(text)

    @staticmethod
    def _fallback_vector(text: str) -> list[float]:
        """
        Deterministic pseudo-embedding derived from text hash.
        Used when the Claude response cannot be parsed.
        Ensures the system never crashes due to an embedding failure.
        """
        import math
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(EMBED_DIM):
            byte_val = h[i % 32]
            angle = (byte_val / 255.0) * 2 * math.pi + i
            vec.append(math.sin(angle))
        # L2-normalise
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def normalise(self, vecs: list[list[float]]) -> "Any":
        """Convert to normalised float32 numpy array for FAISS."""
        import numpy as np  # type: ignore
        arr = np.array(vecs, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return arr / norms

    @property
    def cache_size(self) -> int:
        return len(self._cache)


# ===========================================================================
# Tier 2 — Long-term vector memory (FAISS + Claude embeddings)
# ===========================================================================

@dataclass
class MemoryChunk:
    """
    A single retrievable unit stored in the vector index.

    Attributes:
        id:        Deterministic SHA-256 hash of source + text.
        text:      Raw text that was embedded and stored.
        source:    Who produced this chunk (agent name, tool, …).
        metadata:  Arbitrary annotations (run_id, timestamp, …).
        score:     Cosine similarity populated during retrieval (0–1).
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
    Long-term semantic memory backed by FAISS and Claude embeddings.

    All embeddings are produced by Claude (no sentence-transformers required).
    The index persists to disk between sessions via persist() / load().

    If faiss-cpu is not installed, all operations degrade to no-ops with a
    warning — the rest of the system continues to function without RAG.

    Example::

        vm = VectorMemory(client=anthropic_client, model="claude-haiku-4-5")
        vm.store("The B2B CRM TAM is $50B globally.", source="research")
        chunks = vm.retrieve("market size CRM", k=3)
        for chunk in chunks:
            print(chunk)
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        persist_dir: str | None = None,
    ) -> None:
        from config import settings
        import anthropic

        self._persist_dir = Path(persist_dir or settings.vector_memory_dir)
        self._chunk_size = settings.rag_chunk_size
        self._chunk_overlap = settings.rag_chunk_overlap

        # Use a fast/cheap model for embeddings to minimise cost & latency
        embed_model = model or "claude-haiku-4-5-20251001"
        embed_client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._embedder = ClaudeEmbedder(client=embed_client, model=embed_model)

        self._index: Any = None
        self._chunks: list[MemoryChunk] = []
        self._available = False

        self._try_init_faiss()

    def _try_init_faiss(self) -> None:
        """Attempt to initialise the FAISS index; degrade gracefully on ImportError."""
        try:
            import faiss  # type: ignore
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._available = True
            logger.info("memory.vector.ready", dim=EMBED_DIM, backend="claude-embeddings")
        except ImportError:
            logger.warning(
                "memory.vector.unavailable",
                hint="pip install faiss-cpu",
                note="RAG disabled; system continues without vector memory",
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when faiss-cpu is installed and the index is ready."""
        return self._available

    def store(self, text: str, source: str, **metadata: Any) -> list[MemoryChunk]:
        """
        Chunk, embed (via Claude), and index *text*.

        Args:
            text:       Free-text to index (agent output, search result, …).
            source:     Producer identifier (e.g. ``"research"``).
            **metadata: Arbitrary annotations stored alongside each chunk.

        Returns:
            List of MemoryChunk objects added to the index.
            Empty list when the vector layer is unavailable.
        """
        if not self._available:
            return []

        chunks = self._chunk_text(text, source, **metadata)
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        vecs_raw = self._embedder.embed_batch(texts)
        vecs = self._embedder.normalise(vecs_raw)

        self._index.add(vecs)  # type: ignore[union-attr]
        self._chunks.extend(chunks)

        logger.debug(
            "memory.vector.stored",
            source=source,
            chunks=len(chunks),
            total=len(self._chunks),
            embed_cache=self._embedder.cache_size,
        )
        return chunks

    def retrieve(self, query: str, k: int | None = None) -> list[MemoryChunk]:
        """
        Return the *k* most semantically similar chunks to *query*.

        Embeddings for the query are also cached so repeated identical
        queries never make a second API call.

        Args:
            query: Natural-language query string.
            k:     Number of results (defaults to settings.rag_top_k).

        Returns:
            List of MemoryChunk sorted by descending cosine similarity.
        """
        if not self._available or self._index.ntotal == 0:  # type: ignore[union-attr]
            return []

        from config import settings
        effective_k = min(k or settings.rag_top_k, self._index.ntotal)  # type: ignore[union-attr]

        vecs_raw = self._embedder.embed_batch([query])
        query_vec = self._embedder.normalise(vecs_raw)

        scores, indices = self._index.search(query_vec, effective_k)  # type: ignore[union-attr]

        import dataclasses
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            results.append(dataclasses.replace(self._chunks[idx], score=float(score)))

        logger.debug(
            "memory.vector.retrieve",
            query=query[:60],
            k=effective_k,
            found=len(results),
        )
        return results

    def retrieve_as_context(self, query: str, k: int | None = None) -> str:
        """
        Retrieve relevant chunks and return them as a Markdown block
        ready for injection into a Claude prompt.
        """
        chunks = self.retrieve(query, k=k)
        if not chunks:
            return ""
        lines = ["## Retrieved Memory Context (RAG)\n"]
        for i, chunk in enumerate(chunks, 1):
            lines.append(
                f"### Memory {i} — source: `{chunk.source}`  "
                f"relevance: {chunk.score:.2f}\n{chunk.text}\n"
            )
        return "\n".join(lines)

    def persist(self) -> Path:
        """
        Save the FAISS index and chunk metadata to ``vector_memory_dir``.

        Returns:
            Path to the persistence directory.
        """
        if not self._available:
            raise RuntimeError("Vector memory unavailable — cannot persist.")

        import faiss  # type: ignore

        self._persist_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._persist_dir / "index.faiss"))

        meta = [
            {"id": c.id, "text": c.text, "source": c.source, "metadata": c.metadata}
            for c in self._chunks
        ]
        (self._persist_dir / "chunks.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        logger.info("memory.vector.persisted", path=str(self._persist_dir), chunks=len(self._chunks))
        return self._persist_dir

    def load(self) -> bool:
        """
        Restore a previously persisted FAISS index from disk.

        Returns:
            True on success, False if no persisted index found.
        """
        if not self._available:
            return False

        import faiss  # type: ignore

        idx_path = self._persist_dir / "index.faiss"
        meta_path = self._persist_dir / "chunks.json"

        if not idx_path.exists() or not meta_path.exists():
            logger.debug("memory.vector.no_saved_index")
            return False

        try:
            self._index = faiss.read_index(str(idx_path))
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            self._chunks = [
                MemoryChunk(
                    id=r["id"], text=r["text"],
                    source=r["source"], metadata=r.get("metadata", {}),
                )
                for r in raw
            ]
            logger.info("memory.vector.loaded", chunks=len(self._chunks))
            return True
        except Exception:
            logger.exception("memory.vector.load_error")
            return False

    def clear(self) -> None:
        """Reset the in-memory index (does not delete persisted files)."""
        if self._available:
            import faiss  # type: ignore
            self._index = faiss.IndexFlatIP(EMBED_DIM)
        self._chunks.clear()

    @property
    def size(self) -> int:
        return len(self._chunks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str, source: str, **metadata: Any) -> list[MemoryChunk]:
        """Split *text* into overlapping fixed-size character windows."""
        size, overlap = self._chunk_size, self._chunk_overlap
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
            f"dim={EMBED_DIM} chunks={self.size} "
            f"embed_cache={self._embedder.cache_size}>"
        )


# ===========================================================================
# Unified MemoryManager
# ===========================================================================

class MemoryManager:
    """
    Single object injected into every agent, combining both memory tiers.

    Short-term (KV)::

        mgr.store("run:objective", "Build a SaaS CRM")
        obj = mgr.retrieve("run:objective")

    Long-term (RAG)::

        mgr.index("The global CRM market is $50B.", source="research")
        context = mgr.rag_context("market size CRM software")
        # inject context string into Claude prompt

    Example::

        mgr = MemoryManager()
        mgr.store("ceo:vision", "AI-native CRM")
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
        self.vector: VectorMemory | None
        if vector is not None:
            self.vector = vector
        elif settings.enable_vector_memory:
            self.vector = VectorMemory()
        else:
            self.vector = None

        logger.info(
            "memory.manager.ready",
            kv_backend=type(self.kv._backend).__name__,
            vector_available=self.vector.available if self.vector else False,
            embedding_backend="claude" if self.vector else "disabled",
        )

    # ------------------------------------------------------------------
    # KV pass-through
    # ------------------------------------------------------------------

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in short-term KV memory."""
        self.kv.store(key, value, ttl)

    def retrieve(self, key: str) -> Any | None:
        """Retrieve a value from short-term KV memory."""
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
        Embed (via Claude) and index *text* in long-term vector memory.

        Silently does nothing if the vector layer is unavailable.

        Args:
            text:      Free-text to store.
            source:    Producer identifier (agent name, tool, …).
            **metadata: Annotations attached to every generated chunk.

        Returns:
            List of stored MemoryChunk objects (empty if unavailable).
        """
        if self.vector is None or not self.vector.available:
            return []
        return self.vector.store(text, source, **metadata)

    def rag_context(self, query: str, k: int | None = None) -> str:
        """
        Retrieve the most relevant memory chunks for *query* and return
        them as a Markdown string for prompt injection.

        Returns an empty string when vector memory is unavailable or empty.
        """
        if self.vector is None or not self.vector.available:
            return ""
        return self.vector.retrieve_as_context(query, k=k)

    def persist_vector(self) -> None:
        """Flush the FAISS index and chunk metadata to disk."""
        if self.vector and self.vector.available:
            self.vector.persist()

    def load_vector(self) -> bool:
        """Restore the FAISS index from disk. Returns True on success."""
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
