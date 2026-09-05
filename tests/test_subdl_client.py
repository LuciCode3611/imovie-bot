"""SubDL client: request shape (Persian only, key server-side), the answer
mapping, and the failure modes an owner meets when the key is missing or the
daily quota is gone."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.exceptions import ArchiveTooLargeError, SubdlError
from src.models import MediaKind, SubtitleSummary
from src.models.config import Config
from src.services import subdl as subdl_module
from src.services.subdl import MAX_ARCHIVE_BYTES, SUBS_PER_PAGE, SubdlClient, archive_filename
from src.services.subdl_parsers import SEARCH_PATH

API_KEY = "sekret-key-do-not-leak"

SEARCH_ANSWER = {
    "status": True,
    "results": [{"imdb_id": "tt0816692", "tmdb_id": 157336, "type": "movie", "name": "Interstellar", "sd_id": 123456, "year": 2014}],
    "subtitles": [{"release_name": "Interstellar.2014.1080p.BluRay", "url": "/subtitle/1-2.zip", "language": "FA"}],
}


def _summary(kind: MediaKind = MediaKind.MOVIE) -> SubtitleSummary:
    return SubtitleSummary(title_en="Interstellar", sd_id="123456", kind=kind)


def _config(**kwargs: Any) -> Config:
    return Config(_env_file=None, bot_token="1:abc", subdl_api_key=API_KEY, **kwargs)


def _json_answer(payload: dict, status_code: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status_code, content=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})


def _client(handler: Callable[[httpx.Request], httpx.Response], **config: Any) -> tuple[SubdlClient, list[httpx.Request]]:
    """A client wired to a mock transport that records every request."""
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    return SubdlClient(_config(**config), transport=httpx.MockTransport(record)), sent


async def test_search_asks_for_persian_only_and_returns_titles() -> None:
    client, sent = _client(_json_answer(SEARCH_ANSWER))
    try:
        summaries = await client.search("interstellar")
    finally:
        await client.close()
    assert [s.title_en for s in summaries] == ["Interstellar"]
    assert summaries[0].kind is MediaKind.MOVIE and summaries[0].sd_id == "123456"

    request = sent[0]
    assert request.url.host == "api.subdl.com" and request.url.path == SEARCH_PATH
    params = dict(request.url.params)
    assert params["film_name"] == "interstellar"
    assert params["languages"] == "FA"
    assert params["subs_per_page"] == str(SUBS_PER_PAGE)
    assert params["api_key"] == API_KEY
    assert client.stats["searches"] == 1 and client.stats["requests"] == 1


async def test_details_query_the_title_by_id() -> None:
    client, sent = _client(_json_answer(SEARCH_ANSWER))
    try:
        await client.search("interstellar")
        details = await client.details(_summary())
    finally:
        await client.close()
    params = dict(sent[1].url.params)
    assert params["sd_id"] == "123456" and params["languages"] == "FA"
    assert "film_name" not in params
    # a movie never carries the season filter: it could legitimately match nothing
    assert "full_season" not in params
    assert details.packs[0].files[0].url == "https://dl.subdl.com/subtitle/1-2.zip"
    assert client.stats["titles"] == 1 and client.stats["requests"] == 2


async def test_a_series_asks_for_whole_season_packs() -> None:
    series_answer = {
        "status": True,
        "results": [{"name": "Breaking Bad", "sd_id": 777, "type": "tv", "year": 2008}],
        "subtitles": [
            {"release_name": "Breaking.Bad.S01.720p", "url": "/subtitle/s01.zip", "language": "FA", "season": 1, "full_season": True},
            {"release_name": "Breaking.Bad.S02.720p", "url": "/subtitle/s02.zip", "language": "FA", "season": 2, "full_season": True},
        ],
    }
    client, sent = _client(_json_answer(series_answer))
    try:
        details = await client.details(_summary(MediaKind.SERIES))
    finally:
        await client.close()
    assert dict(sent[0].url.params)["full_season"] == "1"
    assert [pack.label for pack in details.packs] == ["فصل 1", "فصل 2"]
    assert client.stats["requests"] == 1


async def test_a_series_without_a_season_pack_falls_back_to_single_episodes() -> None:
    """The season filter may exclude single-episode uploads — retry once without it
    rather than showing an empty card."""
    episode_answer = {"status": True, "results": [], "subtitles": [{"release_name": "S01E04", "url": "/subtitle/e04.zip", "language": "FA", "season": 1, "episode": 4}]}
    answers = iter([{"status": True, "results": [], "subtitles": []}, episode_answer])
    client, sent = _client(lambda request: httpx.Response(200, content=json.dumps(next(answers)).encode()))
    try:
        details = await client.details(_summary(MediaKind.SERIES))
    finally:
        await client.close()
    assert [dict(request.url.params).get("full_season") for request in sent] == ["1", None]
    assert details.file_count == 1 and details.packs[0].files[0].label == "قسمت 4 · S01E04"
    assert client.stats["titles"] == 1 and client.stats["requests"] == 2


async def test_a_movie_with_no_persian_subtitle_is_not_retried() -> None:
    client, sent = _client(_json_answer({"status": True, "results": [], "subtitles": []}))
    try:
        details = await client.details(_summary())
    finally:
        await client.close()
    assert len(sent) == 1 and details.packs == []


async def test_details_use_the_configured_download_origin() -> None:
    client, _ = _client(_json_answer(SEARCH_ANSWER), subdl_download_url="https://mirror.test")
    try:
        details = await client.details(_summary())
    finally:
        await client.close()
    assert details.packs[0].files[0].url == "https://mirror.test/subtitle/1-2.zip"


async def test_without_a_key_the_client_is_disabled_and_never_calls_out() -> None:
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=json.dumps(SEARCH_ANSWER).encode())

    client = SubdlClient(Config(_env_file=None, bot_token="1:abc"), transport=httpx.MockTransport(record))
    try:
        assert client.enabled is False
        with pytest.raises(SubdlError, match="SUBDL_API_KEY"):
            await client.search("dune")
        with pytest.raises(SubdlError):
            await client.details(_summary())
    finally:
        await client.close()
    assert sent == [] and client.stats["requests"] == 0


async def test_a_transient_transport_error_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subdl_module, "RETRY_DELAY_SECONDS", 0.0)
    calls = {"count": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=json.dumps(SEARCH_ANSWER).encode())

    client = SubdlClient(_config(), transport=httpx.MockTransport(flaky))
    try:
        assert [s.title_en for s in await client.search("interstellar")] == ["Interstellar"]
    finally:
        await client.close()
    assert calls["count"] == 2


async def test_a_dead_source_raises_without_leaking_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subdl_module, "RETRY_DELAY_SECONDS", 0.0)

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot resolve host (key={API_KEY})")

    client = SubdlClient(_config(), transport=httpx.MockTransport(dead))
    try:
        with pytest.raises(SubdlError) as error:
            await client.search("dune")
    finally:
        await client.close()
    assert API_KEY not in str(error.value)


@pytest.mark.parametrize(
    ("status_code", "marker"),
    [(401, "rejected the API key"), (403, "rejected the API key"), (429, "quota"), (500, "500"), (503, "503")],
)
async def test_http_errors_become_source_errors(status_code: int, marker: str) -> None:
    client, _ = _client(lambda request: httpx.Response(status_code, text="nope"))
    try:
        with pytest.raises(SubdlError, match=marker):
            await client.search("dune")
    finally:
        await client.close()


async def test_the_live_unauthorized_body_reads_as_a_key_problem() -> None:
    """Body captured from api.subdl.com without a key."""
    body = {"status": False, "statusCode": 403, "error": "not_authorized", "message": "Not Authorized"}
    client, _ = _client(_json_answer(body))
    try:
        with pytest.raises(SubdlError, match="rejected the API key"):
            await client.search("dune")
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("error_code", "marker"),
    [("rate_limit", "quota"), ("quota_exceeded", "quota"), ("something_new", "something_new")],
)
async def test_api_error_codes_stay_actionable(error_code: str, marker: str) -> None:
    client, _ = _client(_json_answer({"status": False, "error": error_code}))
    try:
        with pytest.raises(SubdlError, match=marker):
            await client.search("dune")
    finally:
        await client.close()


async def test_api_level_failure_is_surfaced_but_truncated() -> None:
    client, _ = _client(_json_answer({"status": False, "error": "Invalid API key" + "x" * 500}))
    try:
        with pytest.raises(SubdlError) as error:
            await client.search("dune")
    finally:
        await client.close()
    assert "Invalid API key" in str(error.value) and len(str(error.value)) < 200


@pytest.mark.parametrize("body", ["<html>not json</html>", "[1, 2, 3]", '"a string"'])
async def test_unparseable_answers_raise(body: str) -> None:
    client, _ = _client(lambda request: httpx.Response(200, text=body))
    try:
        with pytest.raises(SubdlError):
            await client.search("dune")
    finally:
        await client.close()


async def test_empty_result_sets_are_not_errors() -> None:
    client, _ = _client(_json_answer({"status": True, "results": [], "subtitles": []}))
    try:
        assert await client.search("nothing-like-this") == []
        details = await client.details(_summary())
        assert details.packs == [] and details.file_count == 0
    finally:
        await client.close()


async def test_uptime_is_reported_for_the_dashboard() -> None:
    client, _ = _client(_json_answer(SEARCH_ANSWER))
    try:
        assert client.uptime_seconds() >= 0
    finally:
        await client.close()


# --- archive downloads -------------------------------------------------------

ZIP_URL = "https://dl.subdl.com/subtitle/3197651-3213944.zip"
ZIP_BYTES = b"PK\x03\x04" + b"persian subtitle payload"


def _download_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[SubdlClient, list[httpx.Request]]:
    return _client(handler)


async def test_fetch_archive_downloads_the_public_zip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ZIP_BYTES, headers={"Content-Disposition": 'attachment; filename="fa.zip"'})

    client, sent = _download_client(handler)
    try:
        archive = await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()
    assert archive.data == ZIP_BYTES and archive.size == len(ZIP_BYTES)
    assert archive.filename == "fa.zip"
    # the absolute url overrides the API base, and the key never travels with it
    assert sent[0].url.host == "dl.subdl.com" and "api_key" not in str(sent[0].url)
    assert client.stats["downloads"] == 1 and client.stats["requests"] == 0


async def test_fetch_archive_names_the_file_from_the_url_when_no_disposition() -> None:
    client, _ = _download_client(lambda request: httpx.Response(200, content=ZIP_BYTES))
    try:
        assert (await client.fetch_archive(ZIP_URL)).filename == "3197651-3213944.zip"
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("disposition", "url", "expected"),
    [
        ('attachment; filename="Dune.Persian.zip"', "https://x/1.zip", "Dune.Persian.zip"),
        ("attachment; filename*=UTF-8''%D8%B2%DB%8C%D8%B1%D9%86%D9%88%DB%8C%D8%B3.zip", "https://x/1.zip", "زیرنویس.zip"),
        ("attachment; filename=plain.zip", "https://x/1.zip", "plain.zip"),
        ('attachment; filename="../../etc/passwd"', "https://x/1.zip", "passwd.zip"),
        (None, "https://dl.subdl.com/subtitle/9-9.zip", "9-9.zip"),
        (None, "https://dl.subdl.com/subtitle/", "subtitle.zip"),
        ("garbage", "https://dl.subdl.com/subtitle/9-9.zip", "9-9.zip"),
        (None, "https://dl.subdl.com/subtitle/no-extension", "no-extension.zip"),
    ],
)
def test_archive_filename_prefers_the_disposition_and_strips_paths(disposition: str | None, url: str, expected: str) -> None:
    assert archive_filename(disposition, url) == expected


@pytest.mark.parametrize("status_code", [404, 429, 500])
async def test_fetch_archive_raises_on_a_failed_download(status_code: int) -> None:
    client, _ = _download_client(lambda request: httpx.Response(status_code, text="nope"))
    try:
        with pytest.raises(SubdlError, match=str(status_code)):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


async def test_fetch_archive_refuses_an_html_interstitial() -> None:
    """Download hosts answer "limit reached" pages with a 200 — that must never
    be uploaded to a user as a subtitle."""
    client, _ = _download_client(lambda request: httpx.Response(200, text="<html>too many downloads</html>", headers={"Content-Type": "text/html; charset=utf-8"}))
    try:
        with pytest.raises(SubdlError, match="HTML"):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


async def test_fetch_archive_refuses_an_empty_body() -> None:
    client, _ = _download_client(lambda request: httpx.Response(200, content=b"", headers={"Content-Type": "application/zip"}))
    try:
        with pytest.raises(SubdlError, match="empty"):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


async def test_a_declared_oversize_archive_is_rejected_before_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subdl_module, "MAX_ARCHIVE_BYTES", 1024)
    client, _ = _download_client(lambda request: httpx.Response(200, content=b"x", headers={"Content-Length": "999999999"}))
    try:
        with pytest.raises(ArchiveTooLargeError):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


async def test_a_growing_archive_is_cut_off_mid_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Content-Length: the cap is enforced while streaming, chunk by chunk."""
    monkeypatch.setattr(subdl_module, "MAX_ARCHIVE_BYTES", 16)
    client, _ = _download_client(lambda request: httpx.Response(200, content=b"x" * 5000))
    try:
        with pytest.raises(ArchiveTooLargeError):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


async def test_a_dead_download_host_raises_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client, _ = _download_client(dead)
    try:
        with pytest.raises(SubdlError, match="ConnectError"):
            await client.fetch_archive(ZIP_URL)
    finally:
        await client.close()


def test_the_upload_cap_stays_below_telegrams_limit() -> None:
    assert MAX_ARCHIVE_BYTES < 50 * 1024 * 1024
