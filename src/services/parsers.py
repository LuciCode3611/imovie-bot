import json
import re

from selectolax.parser import HTMLParser

from src.exceptions import ParseError
from src.models import MediaKind, MovieDetails, MovieSummary

TITLE_PREFIXES = ("دانلود رایگان سریال ", "دانلود رایگان فیلم ", "دانلود سریال ", "دانلود انیمیشن ", "دانلود فیلم ")


def parse_search(html: HTMLParser) -> list[MovieSummary]:
    results: list[MovieSummary] = []
    for card in html.css('.posts_hoder_archive .item_body_widget[data-type="post"]'):
        link = card.css_first("a.bgbackitem")
        if link is None or not link.attributes.get("href"):
            continue
        slug = link.attributes["href"].rstrip("/").rsplit("/", 1)[-1]
        poster_node = card.css_first("a.bgbackitem img")
        results.append(
            MovieSummary(
                slug=slug,
                title_en=_text(card, ".item-foot-title h3.movie-title") or slug,
                title_fa=None,
                year=_int_or_none(_text(card, ".score .year")),
                poster_url=poster_node.attributes.get("src") if poster_node else None,
                genres=[node.text(strip=True) for node in card.css(".genres_links h3 span") if node.text(strip=True)],
            )
        )
    return results


def parse_movie(html: HTMLParser, slug: str) -> MovieDetails:
    graph = _jsonld_graph(html)
    webpage = _node(graph, "WebPage")
    if not webpage.get("name"):
        raise ParseError("movie page without JSON-LD WebPage name")
    title_en, title_fa = _split_title(webpage["name"])
    poster = _node(graph, "ImageObject").get("url")
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
    return details


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


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None
