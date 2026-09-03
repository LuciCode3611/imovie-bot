import re

from src.models import MovieSummary

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(value: str) -> str:
    """Comparison form: case-insensitive, punctuation and spaces stripped.

    'Spider Man' -> 'spiderman', 'میان‌ستاره‌ای' -> 'میانستاره‌ای' (ZWNJ dropped).
    """
    return _NON_WORD.sub("", value.casefold())


def title_matches(query: str, title: str) -> bool:
    q = normalize_title(query)
    t = normalize_title(title)
    return bool(q) and bool(t) and (q in t or t in q)


def fallback_query(query: str) -> str | None:
    """Second probe for compound words when the site finds nothing.

    WordPress matches whole words, so 'spiderman' never matches the title
    'Spider Man' — the space breaks the substring. A prefix of the longest
    word ('spid') does match; results are then filtered with title_matches.
    Returns None when a stem cannot help (short words).
    """
    longest = max(query.split(), key=len, default="")
    if len(longest) < 6:
        return None
    stem = longest[: max(4, len(longest) // 2)]
    return stem or None


def filter_matches(query: str, results: list[MovieSummary]) -> list[MovieSummary]:
    return [result for result in results if title_matches(query, result.title_en)]
