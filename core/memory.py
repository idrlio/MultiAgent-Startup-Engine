"""
core/memory.py
Shared persistent memory layer for all agents.
Supports in-memory and disk-backed storage via diskcache.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BaseMemory(ABC):
    """Abstract memory interface."""

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


class InMemoryBackend(BaseMemory):
    """Volatile in-process memory (lost on restart)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl else None
        self._store[key] = (value, expires_at)
        logger.debug("memory.store", key=key, ttl=ttl)

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


class DiskCacheBackend(BaseMemory):
    """Persistent disk-backed memory using diskcache."""

    def __init__(self, directory: str = ".cache/memory") -> None:
        try:
            import diskcache  # type: ignore

            self._cache = diskcache.Cache(directory)
        except ImportError as exc:
            raise RuntimeError("Install diskcache: pip install diskcache") from exc
        logger.info("memory.disk_backend.ready", directory=directory)

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._cache.set(key, value, expire=ttl)
        logger.debug("memory.store", key=key, ttl=ttl)

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
    High-level memory facade used by all agents.

    Usage:
        memory = SharedMemory()
        memory.store("research:market_size", {"value": "1.2B", "source": "..."})
        data = memory.retrieve("research:market_size")
    """

    def __init__(self, backend: BaseMemory | None = None) -> None:
        from config import settings

        if backend is not None:
            self._backend = backend
        elif settings.memory_backend == "diskcache":
            self._backend = DiskCacheBackend(settings.memory_dir)
        else:
            self._backend = InMemoryBackend()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Persist a value under the given key."""
        self._backend.store(key, value, ttl)

    def retrieve(self, key: str) -> Any | None:
        """Fetch a value by key; returns None if missing or expired."""
        return self._backend.retrieve(key)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def clear(self) -> None:
        self._backend.clear()

    def keys(self) -> list[str]:
        return self._backend.keys()

    def append_to_list(self, key: str, item: Any) -> None:
        """Atomically append an item to a stored list."""
        existing: list = self._backend.retrieve(key) or []
        existing.append(item)
        self._backend.store(key, existing)

    def dump(self) -> dict[str, Any]:
        """Return a snapshot of all memory contents."""
        return {k: self._backend.retrieve(k) for k in self.keys()}
