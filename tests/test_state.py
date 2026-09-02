from src.models import MediaKind, MovieSummary
from src.repos.state import CardEntry, CallbackState


def _entry() -> CardEntry:
    summary = MovieSummary(slug="interstellar-2014", title_en="Interstellar", kind=MediaKind.MOVIE)
    return CardEntry(summary=summary)


def test_create_returns_short_key() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    assert len(key) == 6
    assert int(key, 16) >= 0


def test_roundtrip_and_mutation() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    entry = state.get(key)
    assert entry is not None and entry.selection == ""
    entry.selection = "dub"
    assert state.get(key).selection == "dub"


def test_expiry_drops_entry() -> None:
    state = CallbackState(ttl=-1)
    key = state.create(_entry())
    assert state.get(key) is None


def test_drop() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    state.drop(key)
    assert state.get(key) is None
