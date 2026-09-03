from src.services.matching import fallback_query, filter_matches, normalize_title, title_matches
from src.models import MediaKind, MovieSummary


def _summary(title: str) -> MovieSummary:
    return MovieSummary(slug="x-2014", title_en=title, kind=MediaKind.MOVIE)


def test_normalize_strips_spaces_punctuation_and_case() -> None:
    assert normalize_title("Spider Man") == "spiderman"
    assert normalize_title("SPIDER-MAN!") == "spiderman"
    assert normalize_title("میان‌ستاره‌ای") == normalize_title("میان ستاره ای")


def test_title_matches_compound_and_phrase_both_ways() -> None:
    assert title_matches("spiderman", "Spider Man") is True
    assert title_matches("spider man", "Spiderman") is True
    assert title_matches("silo", "Silo") is True
    assert title_matches("spiderman", "Interstellar") is False


def test_fallback_query_stems_longest_word() -> None:
    assert fallback_query("spiderman") == "spid"
    assert fallback_query("lanterns") == "lant"
    assert fallback_query("breaking bad") == "brea"


def test_fallback_query_skips_short_words() -> None:
    assert fallback_query("silo") is None
    assert fallback_query("bad") is None


def test_filter_matches_keeps_normalized_hits() -> None:
    results = [_summary("Spider Man"), _summary("Interstellar"), _summary("Spider Man 2")]
    kept = filter_matches("spiderman", results)
    assert [r.title_en for r in kept] == ["Spider Man", "Spider Man 2"]
