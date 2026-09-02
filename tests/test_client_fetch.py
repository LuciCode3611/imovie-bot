import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from src.exceptions import AuthError, NotFoundError
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_SEARCH = (FIXTURES / "search_interstellar.html").read_text(encoding="utf-8")
PUBLIC_MOVIE = (FIXTURES / "movie_interstellar_public.html").read_text(encoding="utf-8")

LOGGED_OUT_MARK = 'class="btnLoginHeader"'
COOKIE = "wordpress_logged_in_abc=user%7C1; Path=/"

AUTHED_SEARCH = PUBLIC_SEARCH.replace(LOGGED_OUT_MARK, "logged-in-nav")
AUTHED_MOVIE = PUBLIC_MOVIE.replace(LOGGED_OUT_MARK, "logged-in-nav")


def _app(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    cookie_ok = "wordpress_logged_in_abc" in request.headers.get("Cookie", "")
    if path == "/sign-in/" and request.method == "POST":
        return httpx.Response(302, headers={"Set-Cookie": COOKIE, "Location": "/"})
    if path == "/" and request.method == "GET":
        if cookie_ok:
            return httpx.Response(200, text=AUTHED_SEARCH)
        return httpx.Response(200, text=PUBLIC_SEARCH)
    if path == "/interstellar-2014/":
        if cookie_ok:
            return httpx.Response(200, text=AUTHED_MOVIE)
        return httpx.Response(200, text=f"<html><div {LOGGED_OUT_MARK}></div></html>")
    if path == "/missing-2000/":
        return httpx.Response(404, text="not found")
    return httpx.Response(404)


def _client(tmp_path) -> ZarfilmClient:
    cfg = Config(
        _env_file=None,
        bot_token="1:abc",
        zarfilm_username="u",
        zarfilm_password="p",
        session_path=tmp_path / "s.json",
    )
    return ZarfilmClient(cfg, transport=httpx.MockTransport(_app))


async def test_search_returns_summaries(tmp_path) -> None:
    client = _client(tmp_path)
    results = await client.search("interstellar")
    assert any(r.slug == "interstellar-2014" for r in results)
    await client.close()


async def test_movie_404_raises_not_found(tmp_path) -> None:
    client = _client(tmp_path)
    with pytest.raises(NotFoundError):
        await client.movie("missing-2000")
    await client.close()


async def test_movie_logs_in_when_logged_out(tmp_path) -> None:
    client = _client(tmp_path)
    details = await client.movie("interstellar-2014")
    assert details.summary.slug == "interstellar-2014"
    await client.close()


async def test_search_transport_retry(tmp_path) -> None:
    state = {"failed_once": False}

    def flaky(request: httpx.Request) -> httpx.Response:
        if not state["failed_once"]:
            state["failed_once"] = True
            raise httpx.ConnectError("boom", request=request)
        return _app(request)

    cfg = Config(
        _env_file=None,
        bot_token="1:abc",
        zarfilm_username="u",
        zarfilm_password="p",
        session_path=tmp_path / "s.json",
    )
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(flaky))
    results = await client.search("interstellar")
    assert isinstance(results, list)
    await client.close()


LOGGED_OUT_BODY = f"<html><div {LOGGED_OUT_MARK}></div></html>"


def _expiry_app(logins_ok: bool) -> Callable[[httpx.Request], httpx.Response]:
    movie_gets = {"count": 0}

    def app(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sign-in/" and request.method == "POST":
            if logins_ok:
                return httpx.Response(302, headers={"Set-Cookie": COOKIE, "Location": "/"})
            return httpx.Response(200, text="<html>login page</html>")
        if path == "/" and request.method == "GET":
            return httpx.Response(200, text=AUTHED_SEARCH)
        if path == "/interstellar-2014/" and request.method == "GET":
            movie_gets["count"] += 1
            if movie_gets["count"] == 1:
                return httpx.Response(200, text=LOGGED_OUT_BODY)
            return httpx.Response(200, text=AUTHED_MOVIE)
        return httpx.Response(404)

    return app


def _expired_client(tmp_path, app: Callable[[httpx.Request], httpx.Response]) -> ZarfilmClient:
    cfg = Config(
        _env_file=None,
        bot_token="1:abc",
        zarfilm_username="u",
        zarfilm_password="p",
        session_path=tmp_path / "s.json",
    )
    return ZarfilmClient(cfg, transport=httpx.MockTransport(app))


async def test_movie_relogins_when_session_expires(tmp_path) -> None:
    client = _expired_client(tmp_path, _expiry_app(logins_ok=True))
    await client.login()
    client._client.cookies.clear()
    client._logged_in = True
    details = await client.movie("interstellar-2014")
    assert details.summary.slug == "interstellar-2014"
    assert client._logged_in is True
    await client.close()


async def test_movie_autherror_when_relogin_persists(tmp_path) -> None:
    client = _expired_client(tmp_path, _expiry_app(logins_ok=False))
    client._logged_in = True
    with pytest.raises(AuthError):
        await client.movie("interstellar-2014")
    await client.close()
