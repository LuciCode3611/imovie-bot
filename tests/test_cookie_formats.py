from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from aiogram.types import Message, User

from src.handlers import admin
from src.models.config import Config
from src.services.parsers import filter_session_cookies, parse_cookies

JSON_ARRAY = (
    '[{"domain": ".zarfilm.com", "name": "wordpress_logged_in_abc", "value": "user%7C1", '
    '"expirationDate": 1790000000, "path": "/", "httpOnly": true, "secure": true}, '
    '{"domain": ".zarfilm.com", "name": "theme", "value": "dark"}, '
    '{"domain": ".zarfilm.com", "name": "broken"}]'
)
JSON_OBJECT = '{"wordpress_logged_in_abc": "user%7C1", "theme": "dark", "count": 3}'
NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    "# This is a generated file! Do not edit.\n"
    "#HttpOnly_.zarfilm.com\tTRUE\t/\tTRUE\t1790000000\twordpress_logged_in_abc\tuser%7C1\n"
    ".zarfilm.com\tTRUE\t/\tFALSE\t1790000000\ttheme\tdark\n"
    "shortline\n"
)
HEADER = "wordpress_logged_in_abc=user%7C1; theme=dark"


def test_parse_cookies_json_array_skips_incomplete_rows() -> None:
    assert parse_cookies(JSON_ARRAY) == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_parse_cookies_json_object_keeps_string_values_only() -> None:
    assert parse_cookies(JSON_OBJECT) == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_parse_cookies_netscape_with_comments_httponly_and_garbage() -> None:
    assert parse_cookies(NETSCAPE) == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_parse_cookies_header_string() -> None:
    assert parse_cookies(HEADER) == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_parse_cookies_invalid_json_falls_back_to_header() -> None:
    assert parse_cookies("{not json at all=1; wordpress_logged_in_abc=user%7C1") == {
        "{not json at all": "1",
        "wordpress_logged_in_abc": "user%7C1",
    }


def test_filter_session_cookies_untouched() -> None:
    assert filter_session_cookies({"wordpress_logged_in_abc": "u", "theme": "dark"}) == {
        "wordpress_logged_in_abc": "u"
    }


class _StubZarfilm:
    def __init__(self) -> None:
        self._client = httpx.Client()
        self.ready = False

    def mark_session_ready(self) -> None:
        self.ready = True


async def test_receive_cookie_accepts_json_array(tmp_path: Path) -> None:
    cfg = Config(_env_file=None, bot_token="1:abc")
    cfg.session_path = tmp_path / "session.json"
    message = AsyncMock(spec=Message)
    message.text = JSON_ARRAY
    message.from_user = User(id=42, is_bot=False, first_name="t")
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    stub = _StubZarfilm()
    await admin.receive_cookie(message, AsyncMock(), cfg, stub)  # type: ignore[arg-type]
    message.delete.assert_awaited_once()
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    assert stub.ready is True
    message.answer.assert_awaited_once()
