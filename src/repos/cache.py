import time
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}

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
        self._data[key] = (value, time.monotonic() + ttl)
