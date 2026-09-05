from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from src.exceptions import ParseError
from src.models import MediaKind
from src.services.subkade_parsers import (
    detect_kind,
    parse_subtitle_page,
    parse_subtitle_search,
    slug_from_url,
    split_title_year,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _html(name: str) -> HTMLParser:
    return HTMLParser((FIXTURES / name).read_text(encoding="utf-8"))


def test_search_parses_cards_in_order() -> None:
    results = parse_subtitle_search(_html("subkade_search_batman.html"))
    assert len(results) == 7
    first = results[0]
    assert first.title_en == "Batman: Knightfall – Part 1"
    assert first.year == 2026
    assert first.kind is MediaKind.MOVIE
    assert first.poster_url and first.poster_url.startswith("https://subkade.ir/wp-content/")
    assert first.page_url and first.page_url.startswith("https://subkade.ir/")
    assert first.slug.endswith("batman-knightfall-part-1-2026")


def test_search_detects_series_from_slug_word_or_poster_season_marker() -> None:
    results = {r.title_en: r for r in parse_subtitle_search(_html("subkade_search_batman.html"))}
    # slug carries «سریالی» (percent-encoded)
    assert results["Batman: The Animated Series"].kind is MediaKind.SERIES
    # old english slug, but the poster is «The-Batman-S05-…»
    assert results["The Batman"].kind is MediaKind.SERIES
    assert results["Batman"].kind is MediaKind.MOVIE
    assert results["Batman"].year == 1943


def test_search_on_empty_page_returns_nothing() -> None:
    assert parse_subtitle_search(HTMLParser("<html><body><p>no</p></body></html>")) == []


def test_movie_page_metadata_and_single_free_pack() -> None:
    details = parse_subtitle_page(_html("subkade_movie_interstellar.html"), "interstellar-2014")
    assert details.summary.title_en == "Interstellar"
    assert details.summary.year == 2014
    assert details.summary.kind is MediaKind.MOVIE
    assert details.summary.poster_url == "https://subkade.ir/wp-content/uploads/2019/07/Interstellar-2014.webp"
    assert details.title_fa == "میان\u200cستاره\u200cای"
    assert details.imdb == "8.7/10"
    assert details.genres == ["درام", "علمی تخیلی", "ماجراجویی"]
    assert details.countries == ["امریکا"]
    assert details.cast == ["Matthew McConaughey", "Anne Hathaway", "Jessica Chastain"]
    assert details.translators and details.translators.startswith("غریبی")
    assert details.sync_note == "هماهنگ با نسخه BluRay"
    assert details.airing is False
    assert details.plot and details.plot.startswith("فیلم میان‌ ستاره‌ ای")
    # VIP boilerplate after the synopsis is cut off
    assert "اشتراک ویژه" not in details.plot
    assert len(details.packs) == 1
    pack = details.packs[0]
    assert pack.label == "فیلم"
    assert [f.url for f in pack.files] == ["https://dl1.subkade.ir/wp-content/uploads/2024/06/Interstellar-2014.zip"]
    assert pack.files[0].label == "زیرنویس فارسی فیلم"


def test_vip_english_and_arabic_lists_are_never_scraped() -> None:
    details = parse_subtitle_page(_html("subkade_movie_interstellar.html"), "interstellar-2014")
    urls = [f.url for pack in details.packs for f in pack.files]
    assert all("dl1.subkade.ir" in url for url in urls)
    assert not any("account/vip" in url for url in urls)


def test_series_page_groups_files_by_season() -> None:
    details = parse_subtitle_page(_html("subkade_series_breaking_bad.html"), "persian-subtitle-breaking-bad")
    assert details.summary.kind is MediaKind.SERIES
    assert details.summary.year == 2008  # from the metadata row (no year in the title)
    assert details.title_fa == "بریکینگ بد"
    assert details.imdb == "9.5/10"
    assert details.airing is True
    assert [pack.label for pack in details.packs] == ["فصل 1", "فصل 2", "فصل 3", "فصل 4", "فصل 5"]
    assert details.packs[4].file_count == 2
    assert details.packs[4].files[1].label == "زیرنویس فارسی قسمت 9 تا 16"
    assert details.file_count == 6


def test_page_without_title_raises() -> None:
    with pytest.raises(ParseError):
        parse_subtitle_page(HTMLParser("<html><body></body></html>"), "x")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("دانلود زیرنویس فیلم Interstellar 2014", ("Interstellar", 2014)),
        ("دانلود زیرنویس سریال Breaking Bad", ("Breaking Bad", None)),
        ("دانلود زیرنویس انیمیشن سریالی Batman: The Animated Series", ("Batman: The Animated Series", None)),
        ("Batman 1943", ("Batman", 1943)),
        ("Blade Runner 2049 2017", ("Blade Runner 2049", 2017)),
    ],
)
def test_split_title_year(raw: str, expected: tuple[str, int | None]) -> None:
    assert split_title_year(raw) == expected


def test_detect_kind_and_slug_helpers() -> None:
    assert detect_kind("persian-subtitle-breaking-bad", "دانلود زیرنویس سریال Breaking Bad") is MediaKind.SERIES
    assert detect_kind("%d8%b3%d8%b1%db%8c%d8%a7%d9%84-lanterns") is MediaKind.SERIES  # «سریال» percent-encoded
    assert detect_kind("persian-subtitle-x", poster_url="https://s/x/Show-S02-217x325.webp") is MediaKind.SERIES
    assert detect_kind("interstellar-2014") is MediaKind.MOVIE
    assert slug_from_url("https://subkade.ir/persian-subtitle-breaking-bad/") == "persian-subtitle-breaking-bad"


def test_sync_note_comes_from_badge_not_a_container() -> None:
    html = HTMLParser(
        """
        <html><body>
        <h1>دانلود زیرنویس فیلم Dune 2021</h1>
        <div class="sk-single-rate">
          <div class="sk-single-rate-number"><div class="sk-single-imdb"><svg></svg><span>8.0 / 10</span></div></div>
          <div class="sk-single-view"><span>بازدید:</span><span>1 هـزار</span></div>
          <div class="sk-single-current"><svg></svg><span>هماهنگ با نسخه WEB-DL</span></div>
        </div>
        <div id="sk-download"><div class="sk-download-list farsi"><ul>
          <li><p class="description">زیرنویس فارسی فیلم</p><a class="link" href="https://dl1.subkade.ir/x/Dune-2021.zip">دانلود زیرنویس</a></li>
        </ul></div></div>
        </body></html>
        """
    )
    details = parse_subtitle_page(html, "dune-2021")
    assert details.sync_note == "هماهنگ با نسخه WEB-DL"
    assert details.imdb == "8.0/10"
    assert details.summary.year == 2021
    assert details.plot is None and details.title_fa is None
    assert details.packs[0].files[0].url.endswith("Dune-2021.zip")


def test_post_without_free_persian_pack_yields_no_packs() -> None:
    html = HTMLParser(
        """
        <html><body>
        <h1>دانلود زیرنویس فیلم Locked 2026</h1>
        <div id="sk-download">
          <div class="sk-download-list english"><ul>
            <li><p class="description">برای دانلود زیرنویس انگلیسی، می‌بایست اشتراک ویژه تهیه نمایید.</p><a class="link vip" href="https://subkade.ir/account/vip/">خرید اشتراک</a></li>
          </ul></div>
        </div>
        </body></html>
        """
    )
    details = parse_subtitle_page(html, "locked-2026")
    assert details.packs == []
    assert details.file_count == 0
