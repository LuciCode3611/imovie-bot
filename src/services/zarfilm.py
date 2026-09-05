import asyncio
import contextlib
import json
import time
from collections.abc import Mapping
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from src.exceptions import AuthError, NotFoundError, SessionExpiredError
from src.models import MovieDetails, MovieSummary
from src.models.config import Config
from src.services.matching import fallback_query, filter_matches
from src.services.parsers import parse_movie, parse_search

BASE_URL = "https://zarfilm.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class ZarfilmClient:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = config
        self._client = httpx.AsyncClient(   
            base_url=config.base_url,
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self._logged_in = False
        self.started_at = time.monotonic()
        self.stats: dict[str, int] = {"requests": 0, "searches": 0, "movies": 0}

    async def close(self) -> None:
        await self._client.aclose()

    def mark_session_ready(self) -> None:
        self._logged_in = True

    def set_cookies(self, cookies: Mapping[str, str]) -> None:
        for name, value in cookies.items():
            self._client.cookies.set(name, value)

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def session_cookies(self) -> dict[str, str]:
        return {name: value for name, value in self._client.cookies.items()}

    def session_ttl_seconds(self) -> int | None:
        """Remaining lifetime of the WordPress login cookie, in seconds.

        A ``wordpress_logged_in_*`` cookie's value embeds the login expiry as
        the second pipe/percent7C-separated field (a unix timestamp)."""
        for name, value in self.session_cookies().items():
            if not name.startswith("wordpress_logged_in"):
                continue
            for sep in ("|", "%7C"):
                parts = value.split(sep)
                if len(parts) >= 2 and parts[1].isdigit():
                    return max(0, int(parts[1]) - int(time.time()))
        return None

    async def session_valid(self) -> bool:
        """Live check: the home page shows the account menu only when logged
        in. Returns False on any transport error or when no session exists."""
        if not self._restore_session() and not self._logged_in:
            return False
        try:
            response = await self._get("/")
        except httpx.HTTPError:
            return False
        logged_out = self.LOGGED_OUT_MARK in response.text
        return not logged_out

    def persist_session(self) -> None:
        jar = {name: value for name, value in self._client.cookies.items()}
        path = Path(self._cfg.session_path)
        path.write_text(json.dumps(jar), encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)

    async def ensure_session(self) -> None:
        if self._logged_in:
            return
        if self._restore_session():
            self._logged_in = True
            return
        raise AuthError("no valid session — owner must send /login with a browser cookie")

    def _restore_session(self) -> bool:
        path = Path(self._cfg.session_path)
        if not path.exists():
            return False
        try:
            cookies: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not any(name.startswith("wordpress_logged_in") for name in cookies):
            return False
        self.set_cookies(cookies)
        return True

    LOGGED_OUT_MARK = "btnLoginHeader"

    async def search(self, query: str) -> list[MovieSummary]:
        results = await self._search_once(query)
        if results:
            return results
        fallback = fallback_query(query)
        if fallback is None:
            return results
        candidates = await self._search_once(fallback)
        return filter_matches(query, candidates) or candidates

    async def _search_once(self, query: str) -> list[MovieSummary]:
        response = await self._get("/", params={"s": query})
        response.raise_for_status()
        self.stats["searches"] += 1
        return parse_search(HTMLParser(response.text))

    async def movie(self, slug: str) -> MovieDetails:
        response = await self._get_logged_in(f"/{slug}/")
        if response.status_code == 404:
            raise NotFoundError(slug)
        response.raise_for_status()
        self.stats["movies"] += 1
        return parse_movie(HTMLParser(response.text), slug)

    async def _get_logged_in(self, path: str) -> httpx.Response:
        await self.ensure_session()
        response = await self._get(path)
        if self.LOGGED_OUT_MARK in response.text:
            self._logged_in = False
            await self.ensure_session()
            response = await self._get(path)
            if self.LOGGED_OUT_MARK in response.text:
                raise SessionExpiredError("session expired — owner must send /login with a fresh browser cookie")
        return response

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        async with self._lock:
            try:
                return await self._client.get(path, **kwargs)
            except httpx.TransportError:
                await asyncio.sleep(1.0)
                return await self._client.get(path, **kwargs)
