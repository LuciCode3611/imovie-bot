import asyncio
import contextlib
import json
import re
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
            base_url=BASE_URL,
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

    async def resolve_trailer(self, trailer_page_url: str) -> str | None:
        """Resolve a zarfilm /play/{id}/trailer/ page to a direct, Telegram-
        streamable video URL (mp4). Returns None if no playable link could be
        found (e.g. subscription wall we can't get past)."""
        try:
            response = await self._get_logged_in(trailer_page_url.replace(BASE_URL, ""))
        except (AuthError, NotFoundError, SessionExpiredError):
            # the play page may be public; try one unauthenticated fetch
            try:
                response = await self._get(trailer_page_url.replace(BASE_URL, ""))
            except httpx.HTTPError:
                return None
        except httpx.HTTPError:
            return None
        html = response.text

        # 1) direct mp4/hls links embedded in the page
        for match in re.finditer(r'https?://[^\s"\'<>]+?\.(?:mp4|m3u8)(?:\?[^\s"\'<>]*)?', html, re.IGNORECASE):
            url = match.group(0).replace("\\/", "/")
            if self._looks_playable(url):
                return url

        # 2) Aparat embed — resolve via the public video API, then the embed page
        aparat_id = self._aparat_id(html)
        if aparat_id:
            video = await self._aparat_video_url(aparat_id)
            if video:
                return video
        return None

    @staticmethod
    def _looks_playable(url: str) -> bool:
        return ".mp4" in url.lower() or ".m3u8" in url.lower()

    @staticmethod
    def _aparat_id(html: str) -> str | None:
        patterns = (
            r"aparat\.com/(?:video/|v/|embed/)([A-Za-z0-9]+)",
            r"aparat\.com/video/embed/([A-Za-z0-9]+)",
            r'"(?:video_uid|videoUid|vid)"\s*:\s*"([A-Za-z0-9]+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None

    async def _aparat_video_url(self, video_uid: str) -> str | None:
        try:
            api = await self._client.get(f"https://www.aparat.com/v1/videohash/byhash/{video_uid}")
            if api.status_code == 200:
                data = api.json()
                for key in ("file_link", "link", "hls_link", "video_link"):
                    url = self._dig(data, key)
                    if url and self._looks_playable(str(url)):
                        return str(url)
                # structured per-quality list
                for quality in self._dig(data, "video") or []:
                    url = quality.get("file") or quality.get("link") if isinstance(quality, dict) else None
                    if url:
                        return str(url)
        except (httpx.HTTPError, ValueError):
            pass
        try:
            embed = await self._client.get(f"https://www.aparat.com/video/video/embed/videohash/{video_uid}/vt/frame")
            match = re.search(r'https?://[^\s"\'<>]+?\.mp4[^\s"\'<>]*', embed.text)
            if match:
                return match.group(0).replace("\\/", "/")
        except httpx.HTTPError:
            return None
        return None

    @staticmethod
    def _dig(obj, key: str):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for value in obj.values():
                found = ZarfilmClient._dig(value, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = ZarfilmClient._dig(item, key)
                if found is not None:
                    return found
        return None

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
