from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from src.exceptions import ParseError
from src.models import MediaKind
from src.services.parsers import parse_movie, parse_search

FIXTURES = Path(__file__).parent / "fixtures"


def test_search_parses_results() -> None:
    html = HTMLParser((FIXTURES / "search_interstellar.html").read_text(encoding="utf-8"))
    results = parse_search(html)
    assert results, "search page should yield at least one result"
    first = next(r for r in results if r.slug == "interstellar-2014")
    assert first.title_en == "Interstellar"
    assert first.year == 2014
    assert "درام" in first.genres
    assert first.poster_url and first.poster_url.startswith("https")


def test_movie_metadata_from_public_page() -> None:
    html = HTMLParser((FIXTURES / "movie_interstellar_public.html").read_text(encoding="utf-8"))
    details = parse_movie(html, "interstellar-2014")
    assert details.summary.title_en == "Interstellar"
    assert details.summary.title_fa == "میان‌ستاره‌ای"
    assert details.summary.year == 2014
    assert details.summary.kind is MediaKind.MOVIE
    assert details.imdb == "8.6"
    assert details.plot and details.plot.startswith("در حالی که")
    assert details.summary.poster_url and "wp-content" in details.summary.poster_url


def test_parse_error_on_garbage() -> None:
    with pytest.raises(ParseError):
        parse_movie(HTMLParser("<html><body></body></html>"), "nothing-2000")
