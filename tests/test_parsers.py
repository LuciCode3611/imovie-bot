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
    assert details.imdb == "8.6/10"
    assert details.plot and details.plot.startswith("در حالی که")
    assert details.summary.poster_url and "wp-content" in details.summary.poster_url
    assert details.summary.genres and "علمی تخیلی" in details.summary.genres


def test_parse_error_on_garbage() -> None:
    with pytest.raises(ParseError):
        parse_movie(HTMLParser("<html><body></body></html>"), "nothing-2000")


def _cards_html(inner: str) -> str:
    return f'<html><body><div class="posts_hoder_archive">{inner}</div></body></html>'


def _card(data_type: str | None, title: str, slug: str) -> str:
    attr = f' data-type="{data_type}"' if data_type else ""
    return (
        f'<div class="item_body_widget{attr and ""}"{attr}>'
        f'<a class="bgbackitem" href="https://zarfilm.com/{slug}/"><img src="/poster.jpg"></a>'
        f'<div class="item-foot-title"><h3 class="movie-title">{title}</h3></div>'
        f'<div class="score"><span class="year">2023</span></div>'
        "</div>"
    )


def test_search_parses_cards_without_data_type_attribute() -> None:
    html = HTMLParser(_cards_html(_card(None, "Silo", "silo-2023")))
    results = parse_search(html)
    assert len(results) == 1
    assert results[0].title_en == "Silo" and results[0].year == 2023


def test_search_parses_series_cards_with_series_kind() -> None:
    html = HTMLParser(_cards_html(_card("tvshow", "دانلود سریال Silo", "silo-2023")))
    results = parse_search(html)
    assert results[0].kind is MediaKind.SERIES


def test_search_parses_movie_cards_as_movie_kind() -> None:
    html = HTMLParser(_cards_html(_card("movie", "Silo", "silo-2023")))
    results = parse_search(html)
    assert results[0].kind is MediaKind.MOVIE


def test_search_titles_have_persian_prefixes_stripped() -> None:
    html = HTMLParser(_cards_html(_card("movie", "دانلود انیمه Black Torch", "black-torch-2025")))
    results = parse_search(html)
    assert results[0].title_en == "Black Torch"


def test_imdb_rating_never_exceeds_ten() -> None:
    from src.services.parsers import _parse_imdb

    def _rating(raw: str | None) -> str | None:
        node = HTMLParser(f'<div class="item imdb"><strong>{raw}</strong></div>')
        return _parse_imdb(node)

    assert _rating("100/10") is None  # malformed value must not render as "0/10"
    assert _rating("100") is None
    assert _rating("8/1017,204 رای") == "8/10"  # real rating glued to vote count
    assert _rating("8.6/10") == "8.6/10"
    assert _rating("10/10") == "10/10"
    assert _rating("7") == "7/10"
    assert _rating(None) is None


def test_split_title_strips_download_prefixes() -> None:
    from src.services.parsers import _split_title

    assert _split_title("دانلود انیمه Black Torch - بلک تورچ") == ("Black Torch", "بلک تورچ")
    assert _split_title("دانلود انیمیشن Spider-Man") == ("Spider-Man", None)
    assert _split_title("دانلود مستند Cosmos") == ("Cosmos", None)
