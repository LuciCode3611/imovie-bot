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


def _parse_string(page: str, slug: str):
    return parse_movie(HTMLParser(page), slug)


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


RAW_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@graph":[{"@type":"WebPage","name":"دانلود انیمه Heavens Feel II lost butterfly 2019 - پروانه"},'
    '{"@type":"ImageObject","url":"https://img.example.com/p.jpg"}]}'
    "</script></head><body>"
    '<div class="single_dlbox"><div class="inner_dl_box_n_single">'
    '<div class="title_rows_dls"><h3>نسخه بدون زیرنویس</h3>'
    '<span class="label_dl_row no_subtitle_dl">بدون زیرنویس</span></div>'
    '<div class="item_row_dl free_row">'
    '<a class="dllink" href="https://dl6.example.com/Movies/Heavens.Feel.II.2019.BD.Remux.mkv">dl</a>'
    '<div class="meta_row"><div class="item_meta_n_dl size_meta">'
    '<span class="label">حجم</span><span class="value">9.2 GB</span></div></div>'
    '<div class="title_side_row"><span class="quality_name">BluRay 1080p Remux</span></div>'
    "</div>"
    '<div class="item_row_dl free_row">'
    '<a class="dllink" href="https://dl6.example.com/Movies/Heavens.Feel.II.2019.RAW.mkv">dl</a>'
    '<div class="title_side_row"><span class="quality_name">RAW</span></div>'
    "</div>"
    "</div></div></body></html>"
)


def test_raw_release_without_dub_or_sub_still_yields_links() -> None:
    """A raw release has no 'dubbed' path segment and may carry no resolution
    token in the filename; the row's own quality badge must still be used."""
    details = _parse_string(RAW_PAGE, "heavens-feel-ii-2019")
    assert details.originals
    assert details.dubs == []
    assert not details.has_dub


def test_raw_release_quality_comes_from_row_badge() -> None:
    """A badge with a resolution is narrowed to it; one without is kept verbatim."""
    details = _parse_string(RAW_PAGE, "heavens-feel-ii-2019")
    qualities = [link.quality for link in details.originals]
    assert qualities == ["1080p", "RAW"]


def test_link_without_any_quality_hint_falls_back() -> None:
    page = (
        '<html><head><script type="application/ld+json">'
        '{"@graph":[{"@type":"WebPage","name":"Movie - فیلم"},'
        '{"@type":"ImageObject","url":"https://img.example.com/p.jpg"}]}'
        "</script></head><body>"
        '<div class="item_row_dl"><a href="https://dl.example.com/movie/Film.2019.Remux.mkv">dl</a></div>'
        "</body></html>"
    )
    details = _parse_string(page, "movie-2019")
    assert [link.quality for link in details.originals] == ["نسخه اصلی"]


def test_row_without_size_does_not_borrow_a_neighbours_size() -> None:
    details = _parse_string(RAW_PAGE, "heavens-feel-ii-2019")
    assert details.originals[0].size == "9.2 GB"
    assert details.originals[1].size is None


def test_anime_title_prefix_is_stripped() -> None:
    details = _parse_string(RAW_PAGE, "heavens-feel-ii-2019")
    assert details.summary.title_en == "Heavens Feel II lost butterfly"
    assert details.summary.title_fa == "پروانه"


def test_non_media_downloads_are_ignored() -> None:
    """The site footer advertises its own apps from the same dl* hosts."""
    page = (
        '<html><head><script type="application/ld+json">'
        '{"@graph":[{"@type":"WebPage","name":"Movie - فیلم"},'
        '{"@type":"ImageObject","url":"https://img.example.com/p.jpg"}]}'
        "</script></head><body>"
        '<div class="item_row_dl"><a href="https://dl.example.com/app/zarmob.apk">app</a>'
        '<div class="title_side_row"><span class="quality_name">1080p</span></div></div>'
        '<div class="item_row_dl"><a href="https://dl.example.com/movie/Film.2019.mkv">dl</a>'
        '<div class="title_side_row"><span class="quality_name">WEB-DL 720p</span></div></div>'
        "</body></html>"
    )
    details = _parse_string(page, "movie-2019")
    assert [link.quality for link in details.originals] == ["720p"]
    assert all(".apk" not in link.url for link in details.originals)
