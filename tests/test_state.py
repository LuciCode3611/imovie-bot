from src.models import MediaKind, MovieSummary
from src.repos.state import CardEntry, CallbackState, SearchEntry


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


def _search_entry() -> SearchEntry:
    return SearchEntry(query="interstellar", pairs=[("aaaaaa", _entry()), ("bbbbbb", _entry())])


def test_create_search_roundtrip() -> None:
    state = CallbackState(ttl=60)
    entry = _search_entry()
    key = state.create_search(entry)
    loaded = state.get_search(key)
    assert loaded is entry
    assert loaded is not None and loaded.total == 2


def test_card_and_search_entries_do_not_cross_types() -> None:
    state = CallbackState(ttl=60)
    ckey = state.create(_entry())
    skey = state.create_search(_search_entry())
    assert state.get(ckey) is not None
    assert state.get(skey) is None
    assert state.get_search(ckey) is None
    assert state.get_search(skey) is not None


def test_search_entry_expiry() -> None:
    state = CallbackState(ttl=-1)
    key = state.create_search(_search_entry())
    assert state.get_search(key) is None
