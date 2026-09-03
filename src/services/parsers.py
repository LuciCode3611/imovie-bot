import json
import re
from urllib.parse import urlparse

from selectolax.parser import HTMLParser
from selectolax.parser import Node

from src.exceptions import ParseError
from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)

TITLE_PREFIXES = ("دانلود رایگان سریال ", "دانلود رایگان فیلم ", "دانلود سریال ", "دانلود انیمیشن ", "دانلود فیلم ")

SITE_ORIGIN = "https://zarfilm.com"
DL_HREF_PREFIX = "https://dl"
SEASON_HEADING_TAGS = ("h2", "h3", "h4")
SEASON_HEADING_WORD = "فصل"
SEASON_LABEL_PATTERN = re.compile(r"فصل[\s\u200c]+\S+")
QUALITY_PATTERN = re.compile(r"\d{3,4}p", re.IGNORECASE)
EPISODE_PATTERN = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(گی[گک]ابایت|مگابایت|کیلوبایت|[GMK]i?B)", re.IGNORECASE)
SIZE_UNITS = {"گیگابایت": "GB", "گیکابایت": "GB", "مگابایت": "MB", "کیلوبایت": "KB"}


def parse_cookie_header(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            name, value = part.strip().split("=", 1)
            cookies[name] = value
    return cookies


def filter_session_cookies(cookies: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in cookies.items() if name.startswith("wordpress_logged_in")}


def parse_cookies(raw: str) -> dict[str, str]:
    """Auto-detect pasted cookie format, trying JSON, then Netscape, then header; domain fields are discarded and all cookies are kept because the jar is per-bot and zarfilm ignores irrelevant entries."""
    text = raw.lstrip()
    if text.startswith(("[", "{")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(data, (list, dict)):
                return _cookies_from_json(data)
    if "\t" in raw:
        netscape = _cookies_from_netscape(raw)
        if netscape:
            return netscape
    return parse_cookie_header(raw)


def _cookies_from_json(data: list | dict) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and item.get("value") is not None:
                cookies[name] = str(item["value"])
    else:
        for name, value in data.items():
            if isinstance(name, str) and isinstance(value, str):
                cookies[name] = value
    return cookies


def _cookies_from_netscape(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#HttpOnly_"):
            stripped = stripped[len("#HttpOnly_") :]
        elif stripped.startswith("#"):
            continue
        fields = stripped.split("\t", 6)
        if len(fields) >= 7:
            cookies[fields[5]] = fields[6]
    return cookies


def parse_search(html: HTMLParser) -> list[MovieSummary]:
    # card data-type varies between post kinds (movies/series) — match any card
    results: list[MovieSummary] = []
    for card in html.css(".posts_hoder_archive .item_body_widget"):
        link = card.css_first("a.bgbackitem")
        if link is None or not link.attributes.get("href"):
            continue
        slug = link.attributes["href"].rstrip("/").rsplit("/", 1)[-1]
        poster_node = card.css_first("a.bgbackitem img")
        title = _text(card, ".item-foot-title h3.movie-title")
        results.append(
            MovieSummary(
                slug=slug,
                title_en=title or slug,
                title_fa=None,
                year=_int_or_none(_text(card, ".score .year")),
                poster_url=_absolute(poster_node.attributes.get("src")) if poster_node else None,
                genres=[node.text(strip=True) for node in card.css(".genres_links h3 span") if node.text(strip=True)],
                kind=_detect_kind(title or ""),
            )
        )
    return results


def parse_movie(html: HTMLParser, slug: str) -> MovieDetails:
    graph = _jsonld_graph(html)
    webpage = _node(graph, "WebPage")
    if not webpage.get("name"):
        raise ParseError("movie page without JSON-LD WebPage name")
    title_en, title_fa = _split_title(webpage["name"])
    poster = _absolute(_node(graph, "ImageObject").get("url"))
    summary = MovieSummary(
        slug=slug,
        title_en=title_en,
        title_fa=title_fa,
        year=_year_from_slug(slug),
        poster_url=poster,
        kind=_detect_kind(webpage["name"]),
    )
    details = MovieDetails(
        summary=summary,
        imdb=_text(html, ".item.imdb strong"),
        plot=_text(html, "div.plot"),
    )
    return _parse_download_box(html, details)


def _parse_download_box(html: HTMLParser, details: MovieDetails) -> MovieDetails:
    seen: set[str] = set()
    seasons: dict[str, Season] = {}
    current: Season | None = None
    for node in html.root.traverse(include_text=False):
        if node.tag in SEASON_HEADING_TAGS:
            if SEASON_HEADING_WORD in node.text():
                label = _season_label(node.text(strip=True))
                current = seasons.setdefault(label, Season(label=label))
            continue
        if node.tag != "a":
            continue
        link = _download_link(node)
        if link is None or link.url in seen:
            continue
        seen.add(link.url)
        if current is not None:
            _add_episode(current, link)
        elif _is_dub(link):
            details.dubs.append(link)
        else:
            details.originals.append(link)
    if seasons:
        details.seasons = list(seasons.values())
        details.summary.kind = MediaKind.SERIES
    return details


def _download_link(anchor: Node) -> DownloadLink | None:
    href = anchor.attributes.get("href") or ""
    if not href.startswith(DL_HREF_PREFIX):
        return None
    quality_match = QUALITY_PATTERN.search(urlparse(href).path) or QUALITY_PATTERN.search(anchor.text())
    if quality_match is None:
        return None
    return DownloadLink(
        quality=quality_match.group(0).lower(),
        url=href,
        size=_nearby_size(anchor),
        host=urlparse(href).netloc or None,
    )


def _nearby_size(anchor: Node) -> str | None:
    node = anchor.parent
    for _ in range(4):
        if node is None or node.tag == "body":
            return None
        if size_match := SIZE_PATTERN.search(node.text()):
            return _normalize_size(size_match.group(1), size_match.group(2))
        node = node.parent
    return None


def _normalize_size(value: str, unit: str) -> str:
    unit = SIZE_UNITS.get(unit, unit.upper()).replace("IB", "B")
    return f"{value} {unit}"


def _is_dub(link: DownloadLink) -> bool:
    return "dubbed" in urlparse(link.url).path.lower()


def _season_label(heading_text: str) -> str:
    match = SEASON_LABEL_PATTERN.search(heading_text)
    return match.group(0).strip() if match else heading_text.strip()


def _add_episode(season: Season, link: DownloadLink) -> None:
    pack = next((q for q in season.qualities if q.quality == link.quality), None)
    if pack is None:
        pack = QualityPack(quality=link.quality)
        season.qualities.append(pack)
    pack.episodes.append(EpisodeLink(label=_episode_label(link.url), url=link.url, size=link.size, host=link.host))


def _episode_label(url: str) -> str:
    match = EPISODE_PATTERN.search(urlparse(url).path)
    if match:
        return f"S{match.group(1).zfill(2)}E{match.group(2).zfill(2)}"
    return urlparse(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace(".", " ")


def _jsonld_graph(html: HTMLParser) -> dict:
    for node in html.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            return data
    return {}


def _node(graph: dict, node_type: str) -> dict:
    for node in graph.get("@graph", []):
        if node.get("@type") == node_type:
            return node
    return {}


def _split_title(name: str) -> tuple[str, str | None]:
    title = name
    for prefix in TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    if " - " in title:
        en, fa = title.rsplit(" - ", 1)
        return _strip_year(en), fa.strip()
    return _strip_year(title), None


def _strip_year(value: str) -> str:
    return re.sub(r"\s+\d{4}$", "", value).strip()


def _detect_kind(title: str) -> MediaKind:
    return MediaKind.SERIES if "سریال" in title or "مجموعه" in title else MediaKind.MOVIE


def _year_from_slug(slug: str) -> int | None:
    match = re.search(r"-(\d{4})$", slug)
    return int(match.group(1)) if match else None


def _text(scope: HTMLParser, selector: str) -> str | None:
    node = scope.css_first(selector)
    return node.text(strip=True) if node else None


def _absolute(url: str | None) -> str | None:
    if url is None:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return SITE_ORIGIN + (url if url.startswith("/") else f"/{url}")


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None
