"""In-memory session cache. Nothing is written to disk; it is cleared on exit (PLAN §9 rule 3)."""

from __future__ import annotations

import threading
from typing import Any

from cachetools import TTLCache

from cfa import config


class SessionCache:
    def __init__(self, maxsize: int = config.CACHE_MAX_ITEMS, ttl: float = config.CACHE_TTL_S) -> None:
        self._data: TTLCache[Any, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def pop(self, key: Any) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


CACHE = SessionCache()
