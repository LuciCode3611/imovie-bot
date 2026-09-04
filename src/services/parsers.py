import json
import re
from urllib.parse import urlparse

from selectolax.parser import HTMLParser, Node

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

TITLE_PREFIXES = (
    "دانلود رایگان سریال ",
    "دانلود رایگان انیمه ",
    "دانلود رایگان انیمیشن ",
    "دانلود رایگان فیلم ",
    "دانلود سریال ",
    "دانلود انیمه ",
    "دانلود انیمیشن ",
    "دانلود فیلم ",
    "دانلود مستند ",
)

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
        raw_title = _text(card, ".item-foot-title h3.movie-title") or ""
        title = _strip_title_prefix(raw_title)
        results.append(
            MovieSummary(
                slug=slug,
                title_en=title or slug,
                title_fa=None,
                year=_int_or_none(_text(card, ".score .year")),
                poster_url=_absolute(poster_node.attributes.get("src")) if poster_node else None,
                genres=[node.text(strip=True) for node in card.css(".genres_links h3 span") if node.text(strip=True)],
                kind=_detect_kind(raw_title),
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
        imdb=_parse_imdb(html),
        plot=_text(html, "div.plot"),
        countries=_parse_countries(html),
        cast=_parse_people(html, ("ستارگان", "بازیگران")),
        runtime=_parse_runtime(html),
        trailer_url=_parse_trailer(html),
    )
    _parse_genres(html, summary)
    return _parse_download_box(html, details)


def _stars_block(html: HTMLParser, labels: tuple[str, ...]) -> list[str]:
    for block in html.css(".stars"):
        label = block.css_first(".label span")
        if label is not None and any(word in label.text() for word in labels):
            values = [
                (anchor.attributes.get("title") or anchor.text(strip=True)).strip()
                for anchor in block.css(".list .item a")
            ]
            return [v for v in values if v]
    return []


def _parse_people(html: HTMLParser, labels: tuple[str, ...]) -> list[str]:
    return _stars_block(html, labels)


def _parse_runtime(html: HTMLParser) -> str | None:
    """Runtime (مدت زمان) — only when the page exposes an explicit
    minute/hour value; the site does not always provide one, so this is best
    effort and returns None (the row is then omitted) when absent."""
    text = html.text(separator=" ")
    match = re.search(r"(\d{1,3})\s*دقیقه", text)
    if match:
        return f"{match.group(1)} دقیقه"
    match = re.search(r"(\d{1,2})\s*ساعت(?:\s*و\s*(\d{1,2})\s*دقیقه)?", text)
    if match:
        hours, minutes = match.group(1), match.group(2)
        return f"{hours} ساعت" + (f" و {minutes} دقیقه" if minutes else "")
    return None


def _parse_imdb(html: HTMLParser) -> str | None:
    """The rating block renders as e.g. ``8/1017,204 رای`` — keep only the
    ``X/Y`` rating, drop the vote count."""
    raw = _text(html, ".item.imdb strong") or _text(html, ".item.imdb")
    if not raw:
        return None
    # the rating block renders as e.g. "8/1017,204 رای" (the /10 is glued to
    # the vote count). Match the score before "/10", bounded so a malformed
    # value such as "100/10" never matches the trailing "0/10".
    match = re.search(r"(?<![\d.])(10(?:\.\d+)?|[0-9](?:\.\d+)?)/10", raw)
    if match and float(match.group(1)) <= 10:
        return f"{match.group(1)}/10"
    # no denominator: only accept a bare standalone 0–10 number when there is
    # no slash at all (so "100/10" can't match the bare "10")
    if "/" not in raw:
        match = re.search(r"(?<![\d.])(10|[0-9](?:\.\d+)?)(?![\d.])", raw)
        if match is not None and float(match.group(1)) <= 10:
            return f"{match.group(1)}/10"
    return None


def _parse_genres(html: HTMLParser, summary: MovieSummary) -> None:
    if summary.genres:
        return
    holder = html.css_first(".genres_holder_single")
    if holder is None:
        return
    summary.genres = [a.text(strip=True) for a in holder.css("a") if a.text(strip=True)]


def _parse_countries(html: HTMLParser) -> list[str]:
    return _stars_block(html, ("کشور", "محصول"))


def _parse_trailer(html: HTMLParser) -> str | None:
    anchor = html.css_first("a.trailer_btn") or html.css_first("a[href*='/play/'][href*='trailer']")
    if anchor is None:
        return None
    href = anchor.attributes.get("href")
    if not href or not href.startswith("http"):
        return None
    return href


def _parse_download_box(html: HTMLParser, details: MovieDetails) -> MovieDetails:
    seasons = _parse_season_rows(html)
    if seasons:
        details.seasons = seasons
        details.summary.kind = MediaKind.SERIES
        return details
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


def _parse_season_rows(html: HTMLParser) -> list[Season]:
    seasons: list[Season] = []
    seen_urls: set[str] = set()
    for row in html.css(".single_dlbox .row_season_n_dl"):
        label = _season_row_label(row)
        season = next((item for item in seasons if item.label == label), None)
        if season is None:
            season = Season(label=label)
            seasons.append(season)
        for quality_row in row.css(".item_quality_n_row"):
            _add_quality_row(season, quality_row, seen_urls)
    return seasons


def _season_row_label(row: Node) -> str:
    node = row.css_first(".title_series_row_n .season_name")
    if node is not None:
        return node.text(strip=True) or "فصل"
    return _season_label(row.text(strip=True)) or "فصل"


def _add_quality_row(season: Season, row: Node, seen_urls: set[str]) -> None:
    links: list[DownloadLink] = []
    for anchor in row.css("a.dllinkhref"):
        link = _download_link(anchor)
        if link is None or link.url in seen_urls:
            continue
        seen_urls.add(link.url)
        links.append(link)
    if not links:
        return
    dubbed = _is_dub_row(row)
    quality = _quality_pack_label(row, links[0])
    pack = next((item for item in season.qualities if item.quality == quality), None)
    if pack is None:
        pack = QualityPack(quality=quality, dubbed=dubbed)
        season.qualities.append(pack)
    elif dubbed:
        pack.dubbed = True
    for link in links:
        if any(episode.url == link.url for episode in pack.episodes):
            continue
        pack.episodes.append(
            EpisodeLink(label=_episode_label(link.url), url=link.url, size=link.size, host=link.host)
        )


def _quality_pack_label(row: Node, link: DownloadLink) -> str:
    label = link.quality
    if link.size:
        label = f"{label} - {link.size}"
    if _is_dub_row(row):
        label += " (دوبله)"
    return label


def _is_dub_row(row: Node) -> bool:
    if row.css_first(".label_row_q_n.dubled_ba"):
        return True
    anchor = row.css_first("a.dllinkhref")
    return bool(anchor and "dubbed" in (anchor.attributes.get("href") or "").lower())


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
        pack = QualityPack(quality=link.quality, dubbed=_is_dub(link))
        season.qualities.append(pack)
    elif _is_dub(link):
        pack.dubbed = True
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


def _strip_title_prefix(name: str) -> str:
    title = name.strip()
    for prefix in TITLE_PREFIXES:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title


def _split_title(name: str) -> tuple[str, str | None]:
    title = _strip_title_prefix(name)
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
