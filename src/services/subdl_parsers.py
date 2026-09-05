"""JSON parsing for the SubDL API (https://subdl.com/api-doc).

Shape of the two answers the bot uses (``GET /api/v1/subtitles``):

search  ``film_name=<q>``   → ``results[]``   titles that match the query
                                              {sd_id, imdb_id, tmdb_id, type, name, year}
                              ``subtitles[]`` files of ``results[0]`` *only*, so every
                                              other title is re-queried by id on tap
title   ``sd_id=<id>``      → ``results[]``   the title itself (fills gaps in the summary)
                              ``subtitles[]`` {release_name, name, url, season, episode,
                                              episode_from, episode_end, full_season,
                                              language, author}

Two rules drive the parsing:

* Persian only — ``languages=FA`` is part of every request *and* each entry is
  re-checked, so a mixed-language answer can never reach a user.
* Public downloads — ``url`` is a path that belongs on ``dl.subdl.com``; it is
  joined onto that origin and its query string is dropped, because the link ends
  up in a button every user can copy (an authenticated link would leak the key).
"""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.models import MediaKind, SubtitleDetails, SubtitleFile, SubtitlePack, SubtitleSummary

SEARCH_PATH = "/api/v1/subtitles"
PERSIAN_LANGUAGE = "FA"
# answers carry a code ("FA"/"fa"), an ISO-639-2 code ("per"/"fas") or a name
PERSIAN_ALIASES = frozenset({"fa", "fas", "per", "persian", "farsi", "فارسی"})
DEFAULT_DOWNLOAD_ORIGIN = "https://dl.subdl.com"
ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z", ".srt", ".sub", ".ass")

MOVIE_PACK_LABEL = "فیلم"
SERIES_PACK_LABEL = "سریال"
SEASON_PACK_LABEL = "فصل {season}"
FULL_SEASON_LABEL = "همه قسمت‌ها"
EPISODE_LABEL = "قسمت {episode}"
EPISODE_RANGE_LABEL = "قسمت {start}–{end}"
FALLBACK_FILE_LABEL = "زیرنویس فارسی"
# scene release names are long; the button adds «دانلود» plus the season heading
# on top and Telegram caps button text at 64 characters
RELEASE_LABEL_LIMIT = 44


def parse_titles(payload: Mapping[str, Any]) -> list[SubtitleSummary]:
    """``results[]`` → one summary per distinct title, in the API's own order."""
    summaries: list[SubtitleSummary] = []
    seen: set[str] = set()
    for item in entries(payload.get("results")):
        summary = parse_title(item)
        if summary is None or summary.key in seen:
            continue
        seen.add(summary.key)
        summaries.append(summary)
    return summaries


def parse_title(item: Mapping[str, Any]) -> SubtitleSummary | None:
    title = clean(item.get("name")) or clean(item.get("original_name")) or clean(item.get("title"))
    if title is None:
        return None
    sd_id = clean(item.get("sd_id"))
    return SubtitleSummary(
        title_en=title,
        kind=media_kind(item.get("type")),
        year=positive_int(item.get("year")),
        sd_id=sd_id,
        imdb_id=clean(item.get("imdb_id")),
        tmdb_id=positive_int(item.get("tmdb_id")),
    )


def title_params(summary: SubtitleSummary) -> dict[str, str]:
    """The narrowest way to address one title again — ids beat a name search."""
    api_type = "tv" if summary.kind is MediaKind.SERIES else "movie"
    if summary.sd_id:
        return {"sd_id": summary.sd_id}
    if summary.imdb_id:
        return {"imdb_id": summary.imdb_id, "type": api_type}
    if summary.tmdb_id:
        return {"tmdb_id": str(summary.tmdb_id), "type": api_type}
    params = {"film_name": summary.title_en}
    if summary.year is not None:
        params["year"] = str(summary.year)
    return params


def parse_details(
    payload: Mapping[str, Any],
    summary: SubtitleSummary,
    download_origin: str = DEFAULT_DOWNLOAD_ORIGIN,
) -> SubtitleDetails:
    """``subtitles[]`` → the title's Persian files, grouped per season."""
    files = [parse_file(item, download_origin) for item in entries(payload.get("subtitles"))]
    return SubtitleDetails(summary=merge_title(summary, payload), packs=group_files([f for f in files if f is not None]))


def parse_file(item: Mapping[str, Any], download_origin: str = DEFAULT_DOWNLOAD_ORIGIN) -> SubtitleFile | None:
    """One subtitle entry, or None when it is not Persian or has no download."""
    if not is_persian(item):
        return None
    url = public_zip_url(item.get("url"), download_origin)
    if url is None:
        return None
    season = positive_int(item.get("season"))
    episode = positive_int(item.get("episode"))
    episode_from = positive_int(item.get("episode_from"))
    episode_end = positive_int(item.get("episode_end"))
    full_season = bool(item.get("full_season"))
    return SubtitleFile(
        label=file_label(item),
        url=url,
        season=season,
        episode=episode,
        episode_from=episode_from,
        episode_end=episode_end,
        full_season=full_season,
        author=clean(item.get("author")),
    )


def group_files(files: list[SubtitleFile]) -> list[SubtitlePack]:
    """Season packs for anything that carries season numbers, one «فیلم» pack
    otherwise — driven by the files themselves, so a mistyped ``type`` cannot
    flatten a series into a single unnamed pile."""
    seasons = sorted({file.season for file in files if file.season is not None})
    if not seasons:
        return [SubtitlePack(label=MOVIE_PACK_LABEL, files=files)] if files else []
    by_season = {season: SubtitlePack(label=SEASON_PACK_LABEL.format(season=season)) for season in seasons}
    loose: list[SubtitleFile] = []
    for file in files:
        pack = by_season.get(file.season) if file.season is not None else None
        (pack.files if pack is not None else loose).append(file)
    packs = [by_season[season] for season in seasons]
    if loose:
        packs.append(SubtitlePack(label=SERIES_PACK_LABEL, files=loose))
    return [pack for pack in packs if pack.files]


def file_label(item: Mapping[str, Any]) -> str:
    """«همه قسمت‌ها · Dune.2024.1080p.WEB» — the episode span first so a series
    card reads top-down, then the release name as far as the button allows."""
    parts = [part for part in (episode_span(item), truncate(release_name(item), RELEASE_LABEL_LIMIT)) if part]
    return " · ".join(parts) if parts else FALLBACK_FILE_LABEL


def episode_span(item: Mapping[str, Any]) -> str | None:
    """Which episodes one archive covers: «همه قسمت‌ها», «قسمت 3», «قسمت 1–10»."""
    if item.get("full_season"):
        return FULL_SEASON_LABEL
    start, end = positive_int(item.get("episode_from")), positive_int(item.get("episode_end"))
    if start is not None and end is not None and end > start:
        return EPISODE_RANGE_LABEL.format(start=start, end=end)
    number = positive_int(item.get("episode")) or start or end
    return EPISODE_LABEL.format(episode=number) if number is not None else None


def release_name(item: Mapping[str, Any]) -> str | None:
    """The scene release the file is synced to; ``name`` (the archive's own file
    name) is the fallback, minus its extension."""
    release = clean(item.get("release_name"))
    if release:
        return release
    name = clean(item.get("name"))
    if name is None:
        return None
    lowered = name.casefold()
    for suffix in ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)].strip(" .-_") or None
    return name


def is_persian(item: Mapping[str, Any]) -> bool:
    """True for Persian entries — and for entries with no language field, since
    the request already asked for ``languages=FA``."""
    for field in ("language", "lang"):
        value = clean(item.get(field))
        if value is not None:
            return value.casefold() in PERSIAN_ALIASES
    return True


def public_zip_url(value: Any, origin: str = DEFAULT_DOWNLOAD_ORIGIN) -> str | None:
    """Absolute, credential-free download url for one subtitle entry.

    The API answers with a path («/subtitle/3197651-3213944.zip») that lives on
    ``dl.subdl.com``; query and fragment are dropped whether the value is
    relative or absolute, so an authenticated link (``…zip?api_key=…``) can
    never be published inside a button.
    """
    raw = clean(value)
    if raw is None:
        return None
    split = urlsplit(raw)
    if split.netloc:  # already absolute (or protocol-relative)
        scheme, netloc = split.scheme or "https", split.netloc
    else:
        base = urlsplit(origin if "://" in origin else f"https://{origin}")
        scheme, netloc = base.scheme or "https", base.netloc
    path = split.path if split.path.startswith("/") else f"/{split.path}"
    path = path.rstrip()
    if not netloc or not path.strip("/"):
        return None
    return urlunsplit((scheme, netloc, path, "", ""))  # query and fragment dropped


def merge_title(summary: SubtitleSummary, payload: Mapping[str, Any]) -> SubtitleSummary:
    """A title answer repeats its own ``results`` entry — use it to fill in
    whatever the search entry was missing (year, ids)."""
    matched = next((item for item in parse_titles(payload) if item.key == summary.key), None)
    if matched is None:
        return summary
    updates = {
        field: getattr(matched, field)
        for field in ("year", "sd_id", "imdb_id", "tmdb_id")
        if getattr(summary, field) in (None, "") and getattr(matched, field) not in (None, "")
    }
    return summary.model_copy(update=updates) if updates else summary


def media_kind(value: Any) -> MediaKind:
    """SubDL types a title "movie" or "tv"."""
    return MediaKind.SERIES if str(value or "").strip().casefold() in {"tv", "series", "show"} else MediaKind.MOVIE


def entries(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def positive_int(value: Any) -> int | None:
    """Int or None — SubDL uses 0 for "not a season/episode", which means None here."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def clean(value: Any) -> str | None:
    """One-line text or None; nested structures are never stringified."""
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return None
    text = " ".join(str(value).split())
    return text or None


def truncate(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
