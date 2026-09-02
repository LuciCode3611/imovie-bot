import asyncio
import json
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from src.exceptions import AuthError, NotFoundError
from src.models import MovieDetails, MovieSummary
from src.models.config import Config
from src.services.parsers import parse_movie, parse_search

BASE_URL = "https://zarfilm.com"
LOGIN_PATH = "/sign-in/"
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

    async def close(self) -> None:
        await self._client.aclose()

    async def login(self) -> None:
        async with self._lock:
            await self._login_locked()

    async def _login_locked(self) -> None:
        self._client.cookies.clear()
        response = await self._client.post(
            LOGIN_PATH,
            data={
                "log": self._cfg.zarfilm_username,
                "pwd": self._cfg.zarfilm_password,
                "wp-submit": "ورود",
                "redirect_to": BASE_URL,
            },
        )
        response.raise_for_status()
        if not any(name.startswith("wordpress_logged_in") for name in self._client.cookies.keys()):
            raise AuthError("login rejected: no session cookie; check credentials or form fields")
        Path(self._cfg.session_path).write_text(json.dumps(dict(self._client.cookies)), encoding="utf-8")
        self._logged_in = True

    async def ensure_session(self) -> None:
        if self._logged_in:
            return
        if self._restore_session():
            self._logged_in = True
            return
        await self._login_locked()

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
        for name, value in cookies.items():
            self._client.cookies.set(name, value)
        return True

    LOGGED_OUT_MARK = "btnLoginHeader"

    async def search(self, query: str) -> list[MovieSummary]:
        response = await self._get("/", params={"s": query})
        response.raise_for_status()
        return parse_search(HTMLParser(response.text))

    async def movie(self, slug: str) -> MovieDetails:
        response = await self._get_logged_in(f"/{slug}/")
        if response.status_code == 404:
            raise NotFoundError(slug)
        response.raise_for_status()
        return parse_movie(HTMLParser(response.text), slug)

    async def _get_logged_in(self, path: str) -> httpx.Response:
        await self.ensure_session()
        response = await self._get(path)
        if self.LOGGED_OUT_MARK in response.text:
            self._logged_in = False
            async with self._lock:
                await self._login_locked()
            response = await self._get(path)
            if self.LOGGED_OUT_MARK in response.text:
                raise AuthError("session expired and re-login did not restore access")
        return response

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        async with self._lock:
            try:
                return await self._client.get(path, **kwargs)
            except httpx.TransportError:
                await asyncio.sleep(1.0)
                return await self._client.get(path, **kwargs)
