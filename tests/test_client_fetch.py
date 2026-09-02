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
FRESH_COOKIE = "user%7C1"

AUTHED_SEARCH = PUBLIC_SEARCH.replace(LOGGED_OUT_MARK, "logged-in-nav")
AUTHED_MOVIE = PUBLIC_MOVIE.replace(LOGGED_OUT_MARK, "logged-in-nav")


def _app(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    cookie_ok = "wordpress_logged_in_abc" in request.headers.get("Cookie", "")
    if path == "/sign-in/":
        raise AssertionError("credential login must never be attempted")
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


def _config(tmp_path: Path) -> Config:
    return Config(_env_file=None, bot_token="1:abc", session_path=tmp_path / "s.json")


def _client(tmp_path: Path) -> ZarfilmClient:
    return ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(_app))


def _seed_session(tmp_path: Path, value: str = FRESH_COOKIE) -> None:
    (tmp_path / "s.json").write_text(
        json.dumps({"wordpress_logged_in_abc": value}),
        encoding="utf-8",
    )


async def test_search_returns_summaries(tmp_path: Path) -> None:
    client = _client(tmp_path)
    results = await client.search("interstellar")
    assert any(r.slug == "interstellar-2014" for r in results)
    await client.close()


async def test_movie_404_raises_not_found(tmp_path: Path) -> None:
    _seed_session(tmp_path)
    client = _client(tmp_path)
    with pytest.raises(NotFoundError):
        await client.movie("missing-2000")
    await client.close()


async def test_movie_uses_restored_cookie_session(tmp_path: Path) -> None:
    _seed_session(tmp_path)
    client = _client(tmp_path)
    details = await client.movie("interstellar-2014")
    assert details.summary.slug == "interstellar-2014"
    await client.close()


async def test_search_transport_retry(tmp_path: Path) -> None:
    state = {"failed_once": False}

    def flaky(request: httpx.Request) -> httpx.Response:
        if not state["failed_once"]:
            state["failed_once"] = True
            raise httpx.ConnectError("boom", request=request)
        return _app(request)

    client = ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(flaky))
    results = await client.search("interstellar")
    assert isinstance(results, list)
    await client.close()


LOGGED_OUT_BODY = f"<html><div {LOGGED_OUT_MARK}></div></html>"


def _expiry_app(session_path: Path) -> Callable[[httpx.Request], httpx.Response]:
    """First movie GET sees an expired session; before returning it rewrites
    session.json (the /login hook), so the mid-flight restore picks up the
    fresh cookie and the retry GET is value-checked against it."""
    movie_gets = {"count": 0}

    def app(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/interstellar-2014/" and request.method == "GET":
            movie_gets["count"] += 1
            if movie_gets["count"] == 1:
                session_path.write_text(
                    json.dumps({"wordpress_logged_in_abc": FRESH_COOKIE}),
                    encoding="utf-8",
                )
                return httpx.Response(200, text=LOGGED_OUT_BODY)
            fresh = FRESH_COOKIE in request.headers.get("Cookie", "")
            return httpx.Response(200, text=AUTHED_MOVIE if fresh else LOGGED_OUT_BODY)
        return _app(request)

    return app


async def test_movie_expiry_without_session_raises_autherror(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.mark_session_ready()
    with pytest.raises(AuthError, match="/login"):
        await client.movie("interstellar-2014")
    assert client._logged_in is False
    await client.close()


async def test_movie_expiry_with_refreshed_cookie_retries_and_parses(tmp_path: Path) -> None:
    client = ZarfilmClient(
        _config(tmp_path),
        transport=httpx.MockTransport(_expiry_app(tmp_path / "s.json")),
    )
    client.mark_session_ready()
    details = await client.movie("interstellar-2014")
    assert details.summary.slug == "interstellar-2014"
    assert client._logged_in is True
    await client.close()
