"""SubDL JSON parsing: titles, Persian-only filtering, season grouping and the
public (key-free) download urls that end up in Telegram buttons."""

import pytest

from src.models import MediaKind, SubtitleFile, SubtitleSummary
from src.services.subdl_parsers import (
    DEFAULT_DOWNLOAD_ORIGIN,
    RELEASE_LABEL_LIMIT,
    clean,
    episode_span,
    file_label,
    group_files,
    is_persian,
    media_kind,
    merge_title,
    parse_details,
    parse_titles,
    positive_int,
    public_zip_url,
    release_name,
    title_params,
)

SEARCH_PAYLOAD = {
    "status": True,
    "results": [
        {"imdb_id": "tt0816692", "tmdb_id": 157336, "type": "movie", "name": "Interstellar", "sd_id": 123456, "first_air_date": None, "year": 2014},
        {"imdb_id": "tt0903747", "tmdb_id": 1396, "type": "tv", "name": "Breaking Bad", "sd_id": 777, "first_air_date": "2008-01-20", "year": 2008},
        # same title twice (the API repeats alternates) — kept once
        {"imdb_id": "tt0816692", "tmdb_id": 157336, "type": "movie", "name": "Interstellar", "sd_id": 123456, "year": 2014},
    ],
    "subtitles": [{"release_name": "Interstellar.2014.1080p.BluRay", "name": "fa.zip", "url": "/subtitle/1-2.zip", "language": "FA"}],
}


def _file(**kwargs) -> SubtitleFile:
    return SubtitleFile(label=kwargs.pop("label", "زیرنویس فارسی"), url=kwargs.pop("url", "https://dl.subdl.com/subtitle/a.zip"), **kwargs)


# --- titles ------------------------------------------------------------------


def test_search_titles_keep_order_and_drop_duplicates() -> None:
    summaries = parse_titles(SEARCH_PAYLOAD)
    assert [s.title_en for s in summaries] == ["Interstellar", "Breaking Bad"]
    first = summaries[0]
    assert first.year == 2014 and first.kind is MediaKind.MOVIE
    assert first.sd_id == "123456" and first.imdb_id == "tt0816692" and first.tmdb_id == 157336
    assert summaries[1].kind is MediaKind.SERIES


def test_search_titles_ignore_nameless_and_non_list_payloads() -> None:
    assert parse_titles({"results": [{"year": 2014}, "junk", {"name": "  "}]}) == []
    assert parse_titles({}) == []
    assert parse_titles({"results": {"name": "not a list"}}) == []


def test_media_kind_maps_api_types() -> None:
    assert media_kind("tv") is MediaKind.SERIES
    assert media_kind("TV") is MediaKind.SERIES
    assert media_kind("series") is MediaKind.SERIES
    assert media_kind("movie") is MediaKind.MOVIE
    assert media_kind(None) is MediaKind.MOVIE


def test_title_params_prefer_the_narrowest_id() -> None:
    summary = SubtitleSummary(title_en="Dune", kind=MediaKind.SERIES, year=2024, sd_id="sd1", imdb_id="tt1", tmdb_id=9)
    assert title_params(summary) == {"sd_id": "sd1"}
    assert title_params(summary.model_copy(update={"sd_id": None})) == {"imdb_id": "tt1", "type": "tv"}
    assert title_params(summary.model_copy(update={"sd_id": None, "imdb_id": None})) == {"tmdb_id": "9", "type": "tv"}
    nameless = summary.model_copy(update={"sd_id": None, "imdb_id": None, "tmdb_id": None})
    assert title_params(nameless) == {"film_name": "Dune", "year": "2024"}
    assert title_params(nameless.model_copy(update={"year": None})) == {"film_name": "Dune"}


def test_summary_key_falls_back_through_ids_to_the_title() -> None:
    assert SubtitleSummary(title_en="Dune", sd_id="sd1", imdb_id="tt1").key == "sd1"
    assert SubtitleSummary(title_en="Dune", imdb_id="tt1").key == "tt1"
    assert SubtitleSummary(title_en="Dune", tmdb_id=9).key == "9"
    assert SubtitleSummary(title_en="Dune").key == "dune"


# --- files -------------------------------------------------------------------


def test_movie_files_land_in_one_pack() -> None:
    details = parse_details(
        {
            "results": [{"name": "Interstellar", "sd_id": 123456, "type": "movie", "year": 2014}],
            "subtitles": [
                {"release_name": "Interstellar.2014.1080p.BluRay", "url": "/subtitle/1-2.zip", "language": "FA"},
                {"release_name": "Interstellar.2014.WEB-DL", "url": "/subtitle/3-4.zip", "language": "fa"},
            ],
        },
        SubtitleSummary(title_en="Interstellar", sd_id="123456"),
    )
    assert details.summary.year == 2014  # filled from the title answer
    assert [pack.label for pack in details.packs] == ["فیلم"]
    assert details.file_count == 2
    assert [f.url for pack in details.packs for f in pack.files] == [
        "https://dl.subdl.com/subtitle/1-2.zip",
        "https://dl.subdl.com/subtitle/3-4.zip",
    ]


def test_series_files_group_by_season_and_label_the_span() -> None:
    details = parse_details(
        {
            "subtitles": [
                {"release_name": "Breaking.Bad.S02.720p", "url": "/subtitle/a.zip", "language": "FA", "season": 2, "full_season": True, "episode_from": 1, "episode_end": 13},
                {"release_name": "Breaking.Bad.S01E03", "url": "/subtitle/b.zip", "language": "FA", "season": 1, "episode": 3},
                {"release_name": "Breaking.Bad.S01", "url": "/subtitle/c.zip", "language": "FA", "season": 1, "episode_from": 1, "episode_end": 7},
            ]
        },
        SubtitleSummary(title_en="Breaking Bad", kind=MediaKind.SERIES, sd_id="777"),
    )
    assert [pack.label for pack in details.packs] == ["فصل 1", "فصل 2"]
    assert [f.label for f in details.packs[0].files] == ["قسمت 3 · Breaking.Bad.S01E03", "قسمت 1–7 · Breaking.Bad.S01"]
    assert details.packs[1].files[0].label == "همه قسمت‌ها · Breaking.Bad.S02.720p"
    assert details.seasons == [1, 2]
    assert details.is_series and details.file_count == 3


def test_season_numbers_group_even_when_the_type_says_movie() -> None:
    details = parse_details(
        {"subtitles": [{"url": "/subtitle/a.zip", "language": "FA", "season": 3}]},
        SubtitleSummary(title_en="Mislabeled", kind=MediaKind.MOVIE, sd_id="1"),
    )
    assert [pack.label for pack in details.packs] == ["فصل 3"]


def test_files_without_a_season_number_collect_in_one_series_pack() -> None:
    packs = group_files([_file(season=2), _file(url="https://dl.subdl.com/subtitle/x.zip"), _file(season=1)])
    assert [(pack.label, len(pack.files)) for pack in packs] == [("فصل 1", 1), ("فصل 2", 1), ("سریال", 1)]
    assert group_files([]) == []


def test_only_persian_files_survive_a_mixed_answer() -> None:
    details = parse_details(
        {
            "subtitles": [
                {"release_name": "fa-release", "url": "/subtitle/fa.zip", "language": "FA"},
                {"release_name": "english", "url": "/subtitle/en.zip", "language": "EN"},
                {"release_name": "arabic", "url": "/subtitle/ar.zip", "lang": "ar"},
                # no language field at all: languages=FA was requested, so it stays
                {"release_name": "unlabelled", "url": "/subtitle/none.zip"},
            ]
        },
        SubtitleSummary(title_en="Mixed", sd_id="1"),
    )
    assert [f.url.rsplit("/", 1)[-1] for pack in details.packs for f in pack.files] == ["fa.zip", "none.zip"]


@pytest.mark.parametrize(
    ("language", "expected"),
    [("FA", True), ("fa", True), ("Farsi", True), ("فارسی", True), ("per", True), ("EN", False), ("en", False), (None, True)],
)
def test_is_persian_accepts_every_alias_the_api_uses(language: str | None, expected: bool) -> None:
    entry = {} if language is None else {"language": language}
    assert is_persian(entry) is expected


def test_entries_without_a_download_url_are_skipped() -> None:
    details = parse_details({"subtitles": [{"release_name": "no link", "language": "FA"}, {"language": "FA"}]}, SubtitleSummary(title_en="X", sd_id="1"))
    assert details.packs == [] and details.file_count == 0


# --- download urls -----------------------------------------------------------


def test_relative_url_becomes_a_public_zip_on_the_download_origin() -> None:
    assert public_zip_url("/subtitle/3197651-3213944.zip") == "https://dl.subdl.com/subtitle/3197651-3213944.zip"
    assert public_zip_url("subtitle/1.zip") == "https://dl.subdl.com/subtitle/1.zip"
    assert public_zip_url("/subtitle/1.zip", "https://dl.example.test") == "https://dl.example.test/subtitle/1.zip"


def test_query_string_never_reaches_a_button() -> None:
    """The key authenticates server-side searches; a link a user can copy must stay anonymous."""
    leaked = "https://dl.subdl.com/subtitle/1.zip?api_key=SUPER-SECRET#top"
    assert public_zip_url(leaked) == "https://dl.subdl.com/subtitle/1.zip"
    assert "SUPER-SECRET" not in (public_zip_url(leaked) or "")


def test_absolute_urls_keep_their_host_but_lose_the_query() -> None:
    assert public_zip_url("https://subdl.com/subtitle/9.zip?x=1") == "https://subdl.com/subtitle/9.zip"
    assert public_zip_url("//dl.subdl.com/subtitle/9.zip") == "https://dl.subdl.com/subtitle/9.zip"


@pytest.mark.parametrize("value", [None, "", "   ", "/", "https://dl.subdl.com", {"url": "/x.zip"}, ["/x.zip"]])
def test_unusable_urls_return_none(value: object) -> None:
    assert public_zip_url(value) is None


def test_details_use_the_configured_download_origin() -> None:
    details = parse_details(
        {"subtitles": [{"url": "/subtitle/1.zip", "language": "FA"}]},
        SubtitleSummary(title_en="X", sd_id="1"),
        download_origin="https://mirror.test",
    )
    assert details.packs[0].files[0].url == "https://mirror.test/subtitle/1.zip"


# --- labels ------------------------------------------------------------------


def test_release_name_prefers_the_scene_release_and_strips_archive_suffixes() -> None:
    assert release_name({"release_name": "Dune.2024.1080p.WEB", "name": "dune-fa.zip"}) == "Dune.2024.1080p.WEB"
    assert release_name({"name": "Dune.Persian.Sub.zip"}) == "Dune.Persian.Sub"
    assert release_name({"name": "no-extension"}) == "no-extension"
    assert release_name({"name": ".zip"}) is None
    assert release_name({}) is None


def test_long_release_names_are_truncated_to_fit_a_button() -> None:
    long_release = "Some.Movie.2024.2160p.UHD.BluRay.x265.10bit.HDR.DTS-HD.MA.5.1-GROUP"
    label = file_label({"release_name": long_release, "language": "FA"})
    assert label.endswith("…") and len(label) == RELEASE_LABEL_LIMIT
    assert label.startswith("Some.Movie.2024")


def test_label_falls_back_to_a_persian_name_when_nothing_is_given() -> None:
    assert file_label({"language": "FA"}) == "زیرنویس فارسی"
    assert episode_span({}) is None


def test_episode_span_wording() -> None:
    assert episode_span({"full_season": True}) == "همه قسمت‌ها"
    assert episode_span({"episode_from": 4, "episode_end": 9}) == "قسمت 4–9"
    assert episode_span({"episode": 12}) == "قسمت 12"
    assert episode_span({"episode_from": 5, "episode_end": 5}) == "قسمت 5"
    assert episode_span({"episode_end": 2}) == "قسمت 2"


# --- helpers -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3), ("7", 7), (0, None), (-1, None), ("", None), (None, None), (True, None), ("abc", None)],
)
def test_positive_int_treats_zero_as_absent(value: object, expected: int | None) -> None:
    assert positive_int(value) == expected


def test_clean_collapses_whitespace_and_refuses_structures() -> None:
    assert clean("  Dune \n Part   Two ") == "Dune Part Two"
    assert clean("") is None and clean(None) is None
    assert clean({"a": 1}) is None and clean(["a"]) is None
    assert clean(2024) == "2024"


def test_merge_title_fills_missing_fields_only() -> None:
    summary = SubtitleSummary(title_en="Interstellar", sd_id="123456", year=2010)
    merged = merge_title(summary, SEARCH_PAYLOAD)
    assert merged.year == 2010  # an explicit year is never overwritten
    assert merged.imdb_id == "tt0816692" and merged.tmdb_id == 157336
    assert merge_title(SubtitleSummary(title_en="Unknown", sd_id="9"), SEARCH_PAYLOAD).imdb_id is None


def test_download_origin_default_is_the_public_host() -> None:
    assert DEFAULT_DOWNLOAD_ORIGIN == "https://dl.subdl.com"
