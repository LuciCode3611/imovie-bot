import re
from pathlib import Path

from selectolax.parser import HTMLParser

from src.models import MediaKind
from src.services.formatting import card_text
from src.services.parsers import parse_movie

FIXTURES = Path(__file__).parent / "fixtures"
SIZE_PATTERN = re.compile(r"^\d+(\.\d+)?\s?(GB|MB|KB)$")


def _parse(name: str, slug: str):
    html = HTMLParser((FIXTURES / name).read_text(encoding="utf-8"))
    return parse_movie(html, slug)


def test_authed_movie_has_original_links() -> None:
    details = _parse("movie_interstellar_authed.html", "interstellar-2014")
    assert details.originals
    for link in details.originals:
        assert re.fullmatch(r"\d{3,4}p", link.quality)
        assert link.url.startswith("https://")


def test_authed_movie_dub_links_separated() -> None:
    details = _parse("movie_interstellar_authed.html", "interstellar-2014")
    assert details.dubs
    assert details.has_dub
    for link in details.dubs:
        assert "dubbed" in link.url.lower()
    for link in details.originals:
        assert "dubbed" not in link.url.lower()


def test_dedup_and_host() -> None:
    details = _parse("movie_interstellar_authed.html", "interstellar-2014")
    links = details.originals + details.dubs
    urls = [link.url for link in links]
    assert len(urls) == len(set(urls))
    for link in links:
        assert link.host and "dl" in link.host


def test_series_page_without_seasons_parses() -> None:
    details = _parse("series_dub_authed.html", "batman-knightfall-2026")
    assert details.seasons == []
    assert not details.is_series
    assert details.originals
    assert details.dubs


def test_real_series_page_yields_seasons_and_sizes() -> None:
    details = _parse("lanterns.html", "lanterns")
    assert details.is_series
    assert details.originals == []
    assert details.dubs == []
    assert [season.label for season in details.seasons] == ["فصل 1"]
    assert len(details.seasons[0].qualities) == 13
    pack = details.seasons[0].qualities[0]
    assert pack.quality == "1080p - 2.2 GB"
    assert [episode.label for episode in pack.episodes] == ["S01E01", "S01E02", "S01E03"]
    assert all(episode.size == "2.2 GB" for episode in pack.episodes)
    assert all(episode.host and "dl" in episode.host for episode in pack.episodes)


def test_real_series_page_keeps_dub_rows_and_skips_sound_tracks() -> None:
    details = _parse("lanterns.html", "lanterns")
    packs = details.seasons[0].qualities
    dub_packs = [pack for pack in packs if pack.quality.endswith("(دوبله)")]
    assert len(dub_packs) == 6
    for pack in dub_packs:
        assert pack.episodes
        for episode in pack.episodes:
            assert "dubbed" in episode.url.lower()
            assert "audio.web" not in episode.url.lower()


def test_real_series_card_header_shows_series_kind() -> None:
    details = _parse("lanterns.html", "lanterns")
    text = card_text(details)
    assert text.startswith("📺 سریال | Lanterns")
    assert "zarfilm" not in text.lower()
    assert "زرفیلم" not in text


def test_size_extraction_best_effort() -> None:
    details = _parse("movie_interstellar_authed.html", "interstellar-2014")
    links = details.originals + details.dubs
    for link in links:
        assert link.size is None or SIZE_PATTERN.match(link.size)
    assert any(link.size is not None for link in links)


def test_season_links_form_seasons_and_flip_kind() -> None:
    page = (
        "<html><head><script type=\"application/ld+json\">"
        '{"@graph":[{"@type":"WebPage","name":"Show - نمایش"},'
        '{"@type":"ImageObject","url":"https://img.example.com/p.jpg"}]}'
        "</script></head><body>"
        "<h3>دانلود فصل اول</h3>"
        '<div class="item_row_dl"><a href="https://dl.example.com/show/S01E01.1080p.mkv">dl</a>'
        '<div class="size_meta"><span class="value">300 MB</span></div></div>'
        '<div class="item_row_dl"><a href="https://dl.example.com/show/S01E02.1080p.mkv">dl</a></div>'
        '<div class="item_row_dl"><a href="https://dl.example.com/show/S01E01.720p.mkv">dl</a>'
        '<div class="size_meta"><span class="value">150 MB</span></div></div>'
        "</body></html>"
    )
    details = parse_movie(HTMLParser(page), "show-s01")
    assert details.summary.kind is MediaKind.SERIES
    assert [season.label for season in details.seasons] == ["فصل اول"]
    packs = {pack.quality: pack for pack in details.seasons[0].qualities}
    assert set(packs) == {"1080p", "720p"}
    assert [ep.label for ep in packs["1080p"].episodes] == ["S01E01", "S01E02"]
    assert packs["720p"].episodes[0].size == "150 MB"
    assert packs["1080p"].episodes[0].size == "300 MB"
    assert packs["1080p"].episodes[1].size is None
    assert details.originals == []
    assert details.dubs == []
