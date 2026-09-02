import asyncio
import json
from pathlib import Path

import httpx

from src.exceptions import AuthError
from src.models.config import Config

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
