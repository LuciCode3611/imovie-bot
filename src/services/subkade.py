"""HTTP client for subkade.ir — free Persian subtitle archive.

No login is needed: the Persian zip on ``dl1.subkade.ir`` is public; only
English/Arabic subtitles sit behind a VIP subscription and are never scraped.
"""

import asyncio
import time

import httpx
from selectolax.parser import HTMLParser

from src.exceptions import NotFoundError
from src.models import SubtitleDetails, SubtitleSummary
from src.models.config import Config
from src.services.matching import fallback_query, title_matches
from src.services.subkade_parsers import parse_subtitle_page, parse_subtitle_search
from src.services.zarfilm import USER_AGENT

DEFAULT_BASE_URL = "https://subkade.ir"


class SubkadeClient:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = config
        self._client = httpx.AsyncClient(
            base_url=config.subkade_base_url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fa,en;q=0.8"},
            timeout=20.0,
            follow_redirects=True,
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self.started_at = time.monotonic()
        self.stats: dict[str, int] = {"requests": 0, "searches": 0, "pages": 0}

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, query: str) -> list[SubtitleSummary]:
        results = await self._search_once(query)
        if results:
            return results
        fallback = fallback_query(query)
        if fallback is None:
            return results
        candidates = await self._search_once(fallback)
        matched = [item for item in candidates if title_matches(query, item.title_en)]
        return matched or candidates

    async def _search_once(self, query: str) -> list[SubtitleSummary]:
        response = await self._get("/", params={"s": query})
        response.raise_for_status()
        self.stats["searches"] += 1
        return parse_subtitle_search(HTMLParser(response.text))

    async def subtitle(self, slug: str) -> SubtitleDetails:
        response = await self._get(f"/{slug}/")
        if response.status_code == 404:
            raise NotFoundError(slug)
        response.raise_for_status()
        self.stats["pages"] += 1
        return parse_subtitle_page(HTMLParser(response.text), slug, page_url=str(response.url))

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        async with self._lock:
            self.stats["requests"] += 1
            try:
                return await self._client.get(path, **kwargs)
            except httpx.TransportError:
                await asyncio.sleep(1.0)
                return await self._client.get(path, **kwargs)
