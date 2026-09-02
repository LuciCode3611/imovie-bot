import json
from pathlib import Path

import httpx
import pytest

from src.exceptions import AuthError
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient


def _app(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/sign-in/":
        raise AssertionError("credential login must never be attempted")
    if request.url.path == "/" and request.method == "GET":
        if "wordpress_logged_in_abc" in request.headers.get("Cookie", ""):
            return httpx.Response(200, text="<html>member home</html>")
        return httpx.Response(200, text='<html><a class="btnLoginHeader">ورود / عضویت</a></html>')
    return httpx.Response(404)


def _config(tmp_path: Path) -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        session_path=tmp_path / "session.json",
    )


async def test_ensure_session_without_session_file_raises_autherror(tmp_path: Path) -> None:
    client = ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(_app))
    with pytest.raises(AuthError, match="/login"):
        await client.ensure_session()
    await client.close()


async def test_ensure_session_with_invalid_session_file_raises_autherror(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.session_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(_app))
    with pytest.raises(AuthError, match="/login"):
        await client.ensure_session()
    await client.close()


async def test_restored_session_skips_login(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.session_path.write_text(
        json.dumps({"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}),
        encoding="utf-8",
    )

    calls = {"requests": 0}

    def counting_app(request: httpx.Request) -> httpx.Response:
        calls["requests"] += 1
        return _app(request)

    client = ZarfilmClient(cfg, transport=httpx.MockTransport(counting_app))
    await client.ensure_session()
    assert calls["requests"] == 0
    assert client._logged_in is True
    assert "wordpress_logged_in_abc" in client._client.cookies
    await client.close()


async def test_mark_session_ready_skips_restore(tmp_path: Path) -> None:
    client = ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(_app))
    client.mark_session_ready()
    await client.ensure_session()
    assert client._logged_in is True
    await client.close()
