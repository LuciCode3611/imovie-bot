"""HTML parsers for subkade.ir (Persian subtitle archive).

Page anatomy (WordPress theme, verified live):

search  ``/?s=<q>``  → ``a.sk-query[href]`` cards with ``.sk-loop-image img`` and an ``h3`` title
post    ``/<slug>/`` → ``h1`` «دانلود زیرنویس فیلم|سریال|انیمیشن ... Title 2014»,
                       ``.sk-single-imdb`` «8.7 / 10», ``.sk-single-genre a``,
                       ``.sk-loop-live`` ribbon «در حال پخش» on airing series,
                       ``ul > li > p.text`` metadata rows (سال انتشار / محصول کشور / بازیگران / مترجمین),
                       ``#sk-download .sk-download-list.farsi li`` → ``p.season`` + ``p.description`` + ``a.link[href]``
                       (English/Arabic lists are VIP-only and carry no direct link — skipped).
"""

import re
from urllib.parse import unquote, urlparse

from selectolax.parser import HTMLParser, Node

from src.exceptions import ParseError
from src.models import MediaKind, SubtitleDetails, SubtitleFile, SubtitlePack, SubtitleSummary

SITE_ORIGIN = "https://subkade.ir"
SEARCH_CARD_SELECTOR = "a.sk-query"
SEARCH_TITLE_SELECTOR = "h3"
DOWNLOAD_BOX_SELECTOR = "#sk-download"
FREE_LIST_SELECTOR = ".sk-download-list.farsi"
DOWNLOAD_ITEM_SELECTOR = "li"
DOWNLOAD_LINK_SELECTOR = "a.link"
AIRING_SELECTOR = ".sk-loop-live"
IMDB_SELECTOR = ".sk-single-imdb"
GENRE_SELECTOR = ".sk-single-genre a"
META_ROW_SELECTOR = "li > p.text"
PLOT_SELECTOR = ".sk-single-content p"

# «دانلود زیرنویس فیلم …» / «دانلود زیرنویس انیمیشن سریالی …» — every kind word
# (and their combinations) is stripped; longer alternatives come first
TITLE_PREFIX = re.compile(r"^\s*دانلود\s+زیرنویس\s+(?:(?:انیمیشن|انیمه|مستند|موزیک ویدیو|سریالی|سریال|فیلم)\s*)*", re.UNICODE)
TRAILING_YEAR = re.compile(r"\s+((?:19|20)\d{2})\s*$")
IMDB_PATTERN = re.compile(r"(\d{1,2}(?:\.\d)?)\s*/\s*10")
SEASON_PATTERN = re.compile(r"فصل[\s\u200c]*\d+")
SUBTITLE_ARCHIVE_EXTENSIONS = (".zip", ".rar", ".srt", ".7z")
SYNC_NOTE_MARKERS = ("هماهنگ با", "تمامی نسخه")
PLOT_MARKER = "چکیده و معرفی:"
PLOT_CUT_MARKER = "شما می‌توانید زیرنویس"
SERIES_WORDS = ("سریال", "سریالی", "مجموعه", "انیمه")
META_LABELS: dict[str, str] = {
    "سال انتشار": "year",
    "محصول کشور": "countries",
    "بازیگران": "cast",
    "ستارگان": "cast",
    "مترجمین زیرنویس": "translators",
    "مترجم زیرنویس": "translators",
}
UNKNOWN_TRANSLATOR = "مشخص نیست"


def parse_subtitle_search(html: HTMLParser) -> list[SubtitleSummary]:
    results: list[SubtitleSummary] = []
    seen: set[str] = set()
    for card in html.css(SEARCH_CARD_SELECTOR):
        href = card.attributes.get("href") or ""
        slug = slug_from_url(href)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        raw_title = _text(card, SEARCH_TITLE_SELECTOR) or card.text(strip=True)
        title, year = split_title_year(raw_title)
        poster_url = _poster_src(card.css_first("img"))
        results.append(
            SubtitleSummary(
                slug=slug,
                title_en=title or unquote(slug),
                year=year,
                poster_url=poster_url,
                kind=detect_kind(href, raw_title, poster_url),
                page_url=href if href.startswith("http") else None,
            )
        )
    return results


def parse_subtitle_page(html: HTMLParser, slug: str, page_url: str | None = None) -> SubtitleDetails:
    heading = html.css_first("h1")
    if heading is None or not heading.text(strip=True):
        raise ParseError("subtitle page without an h1 title")
    raw_title = heading.text(strip=True)
    title, year = split_title_year(raw_title)
    meta = _meta_rows(html)
    poster_url = _poster_url(html)
    kind = detect_kind(slug, raw_title, poster_url)
    if kind is MediaKind.MOVIE and _breadcrumb_says_series(html):
        kind = MediaKind.SERIES
    summary = SubtitleSummary(
        slug=slug,
        title_en=title or unquote(slug),
        year=year or _int_or_none(meta.get("year")),
        poster_url=poster_url,
        kind=kind,
        page_url=page_url or _canonical_url(html),
    )
    plot = _parse_plot(html)
    translators = _first_or_none(meta.get("translators"))
    if translators and UNKNOWN_TRANSLATOR in translators:
        translators = None
    return SubtitleDetails(
        summary=summary,
        title_fa=_persian_title(plot),
        imdb=_parse_imdb(html),
        plot=plot,
        genres=[a.text(strip=True) for a in html.css(GENRE_SELECTOR) if a.text(strip=True)],
        countries=_split_list(meta.get("countries")),
        cast=_split_list(meta.get("cast")),
        translators=translators,
        sync_note=_parse_sync_note(html),
        airing=html.css_first(AIRING_SELECTOR) is not None,
        packs=_parse_packs(html, summary.kind),
    )


# --- download box ---------------------------------------------------------


def _parse_packs(html: HTMLParser, kind: MediaKind) -> list[SubtitlePack]:
    box = html.css_first(DOWNLOAD_BOX_SELECTOR) or html.root
    scope = box.css_first(FREE_LIST_SELECTOR) or box
    packs: list[SubtitlePack] = []
    seen_urls: set[str] = set()
    for item in scope.css(DOWNLOAD_ITEM_SELECTOR):
        anchor = item.css_first(DOWNLOAD_LINK_SELECTOR) or item.css_first("a[href]")
        url = _archive_url(anchor)
        if url is None or url in seen_urls:
            continue
        seen_urls.add(url)
        label = _pack_label(item, kind)
        pack = next((p for p in packs if p.label == label), None)
        if pack is None:
            pack = SubtitlePack(label=label)
            packs.append(pack)
        pack.files.append(SubtitleFile(label=_file_label(item, anchor), url=url))
    if packs:
        return packs
    # defensive: theme markup drifted — collect any archive links in the box
    fallback = SubtitlePack(label="فیلم" if kind is MediaKind.MOVIE else "زیرنویس")
    for anchor in box.css("a[href]"):
        url = _archive_url(anchor)
        if url is None or url in seen_urls:
            continue
        seen_urls.add(url)
        fallback.files.append(SubtitleFile(label=anchor.text(strip=True) or "دانلود زیرنویس", url=url))
    return [fallback] if fallback.files else []


def _archive_url(anchor: Node | None) -> str | None:
    if anchor is None:
        return None
    href = (anchor.attributes.get("href") or "").strip()
    if not href.startswith("http"):
        return None
    path = urlparse(href).path.lower()
    return href if path.endswith(SUBTITLE_ARCHIVE_EXTENSIONS) else None


def _pack_label(item: Node, kind: MediaKind) -> str:
    season = _text(item, "p.season") or _text(item, ".season")
    if season:
        match = SEASON_PATTERN.search(season)
        return (match.group(0) if match else season).strip()
    return "فیلم" if kind is MediaKind.MOVIE else "زیرنویس"


def _file_label(item: Node, anchor: Node) -> str:
    description = _text(item, "p.description") or _text(item, ".description")
    if description:
        return description
    text = anchor.text(strip=True)
    return text if text and text != "دانلود زیرنویس" else "زیرنویس فارسی"


# --- metadata ---------------------------------------------------------------


def _meta_rows(html: HTMLParser) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for node in html.css(META_ROW_SELECTOR):
        label = node.text(strip=True).rstrip(":").strip()
        field = META_LABELS.get(label)
        if field is None:
            continue
        parent = node.parent
        if parent is None:
            continue
        values = [a.text(strip=True) for a in parent.css("a") if a.text(strip=True)]
        if not values:
            # plain-text rows (cast, translators) hold the value as the li's
            # remaining text after the label
            remainder = parent.text(separator=" ", strip=True)
            if remainder.startswith(node.text(strip=True)):
                remainder = remainder[len(node.text(strip=True)) :]
            values = [remainder.strip(" :\u200c")] if remainder.strip(" :\u200c") else []
        if values:
            rows[field] = values
    return rows


def _split_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    if len(values) > 1:
        return values
    parts = re.split(r"\s*(?:,|،)\s*", values[0])
    return [part.strip() for part in parts if part.strip()]


def _first_or_none(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _parse_imdb(html: HTMLParser) -> str | None:
    raw = _text(html, IMDB_SELECTOR)
    if not raw:
        return None
    match = IMDB_PATTERN.search(raw)
    if match is None or float(match.group(1)) > 10:
        return None
    return f"{match.group(1)}/10"


def _parse_sync_note(html: HTMLParser) -> str | None:
    for node in html.css("span, p, div"):
        text = node.text(strip=True)
        if text and len(text) <= 60 and any(marker in text for marker in SYNC_NOTE_MARKERS):
            return text
    return None


def _parse_plot(html: HTMLParser) -> str | None:
    for node in html.css(PLOT_SELECTOR):
        text = node.text(separator=" ", strip=True)
        if PLOT_MARKER in text:
            plot = text.split(PLOT_MARKER, 1)[1]
            # drop the boilerplate about VIP subscriptions that follows the synopsis
            plot = plot.split(PLOT_CUT_MARKER, 1)[0]
            plot = re.sub(r"\s+", " ", plot).strip(" .\u200c")
            return plot + "." if plot else None
    return None


_FA_TITLE = re.compile(r"^(?:فیلم|سریال|انیمیشن|انیمه|مستند)\s+(.+?)\s*\(به زبان انگلیسی", re.UNICODE)


def _persian_title(plot: str | None) -> str | None:
    """The synopsis opens with «فیلم میان‌ ستاره‌ ای (به زبان انگلیسی: Interstellar)»
    — lift the Persian title out of it."""
    if not plot:
        return None
    match = _FA_TITLE.search(plot)
    if match is None:
        return None
    title = re.sub(r"\s*\u200c\s*", "\u200c", match.group(1)).strip()
    return title or None


def _poster_url(html: HTMLParser) -> str | None:
    node = html.css_first(".sk-single-image img") or html.css_first("img.wp-post-image")
    if node is None:
        return None
    return _poster_src(node)


def _canonical_url(html: HTMLParser) -> str | None:
    node = html.css_first('link[rel="canonical"]') or html.css_first('meta[property="og:url"]')
    if node is None:
        return None
    value = node.attributes.get("href") or node.attributes.get("content") or ""
    return value if value.startswith("http") else None


def _breadcrumb_says_series(html: HTMLParser) -> bool:
    crumb = html.css_first(".sk_breadcrumb")
    return crumb is not None and any(word in crumb.text() for word in SERIES_WORDS)


def _poster_src(node: Node | None) -> str | None:
    if node is None:
        return None
    for attr in ("data-src", "src", "data-lazy-src"):
        value = (node.attributes.get(attr) or "").strip()
        if value.startswith("http"):
            return value
    return None


# --- titles / slugs ---------------------------------------------------------


def split_title_year(raw: str) -> tuple[str, int | None]:
    """«دانلود زیرنویس فیلم Interstellar 2014» → ("Interstellar", 2014)."""
    title = TITLE_PREFIX.sub("", raw or "").strip()
    year = None
    match = TRAILING_YEAR.search(title)
    if match:
        year = int(match.group(1))
        title = title[: match.start()].strip()
    return title, year


SEASON_FILE_MARKER = re.compile(r"[-_]S\d{2}(?:[-_.]|$)", re.IGNORECASE)


def detect_kind(href_or_slug: str, title: str = "", poster_url: str | None = None) -> MediaKind:
    """Series when the (decoded) slug or title says سریال/انیمه, or when the
    poster file carries a season marker («Breaking-Bad-S01.webp») — the old
    ``persian-subtitle-<name>`` slugs carry no kind word at all."""
    slug = unquote(href_or_slug)
    if any(word in slug or word in title for word in SERIES_WORDS):
        return MediaKind.SERIES
    if poster_url and SEASON_FILE_MARKER.search(urlparse(poster_url).path.rsplit("/", 1)[-1]):
        return MediaKind.SERIES
    return MediaKind.MOVIE


def slug_from_url(url: str) -> str:
    path = urlparse(url).path if url.startswith("http") else url
    return path.strip("/").rsplit("/", 1)[-1]


def _text(scope: HTMLParser | Node, selector: str) -> str | None:
    node = scope.css_first(selector)
    return node.text(strip=True) if node else None


def _int_or_none(values: list[str] | None) -> int | None:
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None
