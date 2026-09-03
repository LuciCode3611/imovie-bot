import time
from typing import Any


class TTLCache:
    def __init__(self, maxsize: int = 256) -> None:
        self._data: dict[str, tuple[Any, float]] = {}
        self._maxsize = maxsize

    async def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires < time.monotonic():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if key not in self._data and len(self._data) >= self._maxsize:
            self._evict()
        self._data[key] = (value, time.monotonic() + ttl)

    def _evict(self) -> None:
        now = time.monotonic()
        for key in [key for key, (_, expires) in self._data.items() if expires < now]:
            del self._data[key]
        while len(self._data) >= self._maxsize:
            self._data.pop(next(iter(self._data)))
