import secrets
import time
from dataclasses import dataclass, field

from src.models import MovieDetails, MovieSummary, SubtitleDetails, SubtitleSummary


@dataclass
class CardEntry:
    summary: MovieSummary
    details: MovieDetails | None = None
    selection: str = ""
    pack: int | None = None
    rich: bool = False  # True once the card was rendered as a Bot API 10.1 rich message
    ep_page: int = 0  # classic episode view: visible page (5/page)
    copy_chunk: int = 0  # which "copy all links" 256-char chunk is shown


@dataclass
class SearchEntry:
    """One search's full result set + the callback keys of its cards, so any
    page of the results can be rebuilt without re-querying the site."""

    query: str
    pairs: list[tuple[str, CardEntry]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.pairs)


@dataclass
class SubtitleCardEntry:
    """A subkade.ir subtitle post opened from the subtitle search results."""

    summary: SubtitleSummary
    details: SubtitleDetails | None = None
    rich: bool = False  # True once rendered as a Bot API 10.1 rich message


@dataclass
class SubtitleSearchEntry:
    query: str
    pairs: list[tuple[str, SubtitleCardEntry]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.pairs)


Entry = CardEntry | SearchEntry | SubtitleCardEntry | SubtitleSearchEntry


class CallbackState:
    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[Entry, float]] = {}

    def create(self, entry: CardEntry) -> str:
        return self._store(entry)

    def create_search(self, entry: SearchEntry) -> str:
        return self._store(entry)

    def create_subtitle(self, entry: SubtitleCardEntry) -> str:
        return self._store(entry)

    def create_subtitle_search(self, entry: SubtitleSearchEntry) -> str:
        return self._store(entry)

    def get(self, key: str) -> CardEntry | None:
        entry = self._load(key)
        return entry if isinstance(entry, CardEntry) else None

    def get_search(self, key: str) -> SearchEntry | None:
        entry = self._load(key)
        return entry if isinstance(entry, SearchEntry) else None

    def get_subtitle(self, key: str) -> SubtitleCardEntry | None:
        entry = self._load(key)
        return entry if isinstance(entry, SubtitleCardEntry) else None

    def get_subtitle_search(self, key: str) -> SubtitleSearchEntry | None:
        entry = self._load(key)
        return entry if isinstance(entry, SubtitleSearchEntry) else None

    def drop(self, key: str) -> None:
        self._data.pop(key, None)

    def _store(self, entry: Entry) -> str:
        self._sweep()
        key = secrets.token_hex(3)
        self._data[key] = (entry, time.monotonic() + self._ttl)
        return key

    def _load(self, key: str) -> Entry | None:
        item = self._data.get(key)
        if item is None:
            return None
        entry, expires = item
        if expires < time.monotonic():
            del self._data[key]
            return None
        return entry

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [key for key, (_, expires) in self._data.items() if expires < now]
        for key in expired:
            del self._data[key]
