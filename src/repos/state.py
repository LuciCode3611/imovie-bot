import secrets
import time
from dataclasses import dataclass

from src.models import MovieDetails, MovieSummary


@dataclass
class CardEntry:
    summary: MovieSummary
    details: MovieDetails | None = None
    selection: str = ""


class CallbackState:
    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[CardEntry, float]] = {}

    def create(self, entry: CardEntry) -> str:
        self._sweep()
        key = secrets.token_hex(3)
        self._data[key] = (entry, time.monotonic() + self._ttl)
        return key

    def get(self, key: str) -> CardEntry | None:
        item = self._data.get(key)
        if item is None:
            return None
        entry, expires = item
        if expires < time.monotonic():
            del self._data[key]
            return None
        return entry

    def drop(self, key: str) -> None:
        self._data.pop(key, None)

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [key for key, (_, expires) in self._data.items() if expires < now]
        for key in expired:
            del self._data[key]
