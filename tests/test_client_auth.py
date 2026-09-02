import json
from pathlib import Path

import httpx
import pytest

from src.exceptions import AuthError
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient

LOGIN_FORM = {"log": "u", "pwd": "p"}


def _app(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/sign-in/" and request.method == "POST":
        form = dict(pair.split("=", 1) for pair in request.content.decode().split("&"))
        if form.get("log") == "u" and form.get("pwd") == "p":
            return httpx.Response(
                302,
                headers={"Set-Cookie": "wordpress_logged_in_abc=user%7C1; Path=/", "Location": "/"},
            )
        return httpx.Response(200, text="<html>login page</html>")
    if request.url.path == "/" and request.method == "GET":
        if "wordpress_logged_in_abc" in request.headers.get("Cookie", ""):
            return httpx.Response(200, text="<html>member home</html>")
        return httpx.Response(200, text='<html><a class="btnLoginHeader">ورود / عضویت</a></html>')
    return httpx.Response(404)


def _config(tmp_path: Path) -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        zarfilm_username="u",
        zarfilm_password="p",
        session_path=tmp_path / "session.json",
    )


async def test_login_success_persists_cookies(tmp_path: Path) -> None:
    client = ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(_app))
    await client.login()
    saved = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert any(key.startswith("wordpress_logged_in") for key in saved)
    await client.close()


async def test_login_bad_credentials_raises(tmp_path: Path) -> None:
    cfg = Config(_env_file=None, bot_token="1:abc", zarfilm_username="wrong", zarfilm_password="x", session_path=tmp_path / "s.json")
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(_app))
    with pytest.raises(AuthError):
        await client.login()
    await client.close()


async def test_restored_session_skips_login(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    first = ZarfilmClient(cfg, transport=httpx.MockTransport(_app))
    await first.login()
    await first.close()

    calls = {"posts": 0}

    def counting_app(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sign-in/":
            calls["posts"] += 1
        return _app(request)

    second = ZarfilmClient(cfg, transport=httpx.MockTransport(counting_app))
    await second.ensure_session()
    assert calls["posts"] == 0
    await second.close()
