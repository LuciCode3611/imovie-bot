"""HTTP client for the SubDL API — Persian subtitles only.

``SUBDL_API_KEY`` (set on the host, e.g. Railway) authenticates every request
and stays server-side: the search runs here, while downloads are the public
``dl.subdl.com`` zip links users tap in Telegram. A free key allows 2,000
requests/day, so results are cached like every other source in this bot.
"""

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx

from src.exceptions import SubdlError
from src.models import MediaKind, SubtitleDetails, SubtitleSummary
from src.models.config import Config
from src.services.subdl_parsers import (
    PERSIAN_LANGUAGE,
    SEARCH_PATH,
    parse_details,
    parse_titles,
    title_params,
)

# the API caps subs_per_page at 30 — one card's worth of alternative releases
SUBS_PER_PAGE = 30
TIMEOUT_SECONDS = 20.0
RETRY_DELAY_SECONDS = 0.5


class SubdlClient:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = config
        self._client = httpx.AsyncClient(
            base_url=config.subdl_base_url,
            headers={"Accept": "application/json", "Accept-Language": "fa,en;q=0.8"},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self.started_at = time.monotonic()
        self.stats: dict[str, int] = {"requests": 0, "searches": 0, "titles": 0}

    @property
    def enabled(self) -> bool:
        """False without an API key — callers say so instead of firing a request
        that SubDL would reject."""
        return bool(self._cfg.subdl_api_key)

    async def close(self) -> None:
        await self._client.aclose()

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    async def search(self, query: str) -> list[SubtitleSummary]:
        """Titles matching a free-text query (SubDL does its own fuzzy fallback)."""
        payload = await self._get({"film_name": query})
        self.stats["searches"] += 1
        return parse_titles(payload)

    async def details(self, summary: SubtitleSummary) -> SubtitleDetails:
        """Persian subtitle files of one title.

        ``full_season=1`` asks for whole-season zips — what a series card wants
        (one button per season instead of 30 single episodes). It is never sent
        for a movie, where a season filter could legitimately match nothing, and
        a series that comes back empty is retried without it so single-episode
        files still reach the user.
        """
        params = title_params(summary)
        series = summary.kind is MediaKind.SERIES
        details = await self._details(params, summary, full_season=series)
        if series and not details.packs:
            details = await self._details(params, summary, full_season=False)
        self.stats["titles"] += 1
        return details

    async def _details(self, params: Mapping[str, str], summary: SubtitleSummary, *, full_season: bool) -> SubtitleDetails:
        query = {**params, "full_season": 1} if full_season else dict(params)
        payload = await self._get(query)
        return parse_details(payload, summary, download_origin=self._cfg.subdl_download_url)

    async def _get(self, params: Mapping[str, str | int]) -> dict[str, Any]:
        if not self.enabled:
            raise SubdlError("SUBDL_API_KEY is not set — the subtitle source is disabled")
        query = {
            "api_key": self._cfg.subdl_api_key,
            "languages": PERSIAN_LANGUAGE,
            "subs_per_page": SUBS_PER_PAGE,
            "client": "custom_integration",
            **params,
        }
        async with self._lock:  # one request in flight: the daily quota is account-wide
            self.stats["requests"] += 1
            response = await self._request(query)
        return _payload(response)

    async def _request(self, query: Mapping[str, str | int]) -> httpx.Response:
        try:
            return await self._client.get(SEARCH_PATH, params=query)
        except httpx.TransportError:
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            try:
                return await self._client.get(SEARCH_PATH, params=query)
            except httpx.TransportError as exc:
                # class name only: an httpx message can quote the url (and the key in it)
                raise SubdlError(f"SubDL unreachable ({exc.__class__.__name__})") from exc


# error codes SubDL puts in the body — observed live:
# {"status": false, "statusCode": 403, "error": "not_authorized", "message": "Not Authorized"}
AUTH_ERROR_CODES = frozenset({"not_authorized", "unauthorized", "invalid_api_key", "forbidden"})
QUOTA_ERROR_CODES = frozenset({"rate_limit", "rate_limited", "too_many_requests", "quota_exceeded", "daily_limit_reached"})


def _payload(response: httpx.Response) -> dict[str, Any]:
    """Validate one answer. Every message stays free of the key and the url."""
    if response.status_code in (401, 403):
        raise SubdlError("SubDL rejected the API key")
    if response.status_code == 429:
        raise SubdlError("SubDL quota or rate limit reached")
    if response.status_code >= 400:
        raise SubdlError(f"SubDL answered {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise SubdlError("SubDL answered with a non-JSON body") from exc
    if not isinstance(data, dict):
        raise SubdlError("SubDL answered with an unexpected JSON shape")
    if data.get("status") is False:
        raise SubdlError(_error_text(data))
    return data


def _error_text(data: Mapping[str, Any]) -> str:
    """An actionable message from the body's ``error`` code — a bad key must read
    like a bad key, not like a generic outage."""
    code = str(data.get("error") or data.get("message") or "unknown").strip()
    lowered = code.casefold()
    if lowered in AUTH_ERROR_CODES or data.get("statusCode") in (401, 403):
        return "SubDL rejected the API key"
    if lowered in QUOTA_ERROR_CODES or data.get("statusCode") == 429:
        return "SubDL quota or rate limit reached"
    return f"SubDL error: {code[:120]}"
