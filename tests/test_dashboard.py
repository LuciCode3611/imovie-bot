from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from aiogram.types import Message, User

from src.handlers import admin
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient


def _cfg(owner: int = 42) -> Config:
    return Config(_env_file=None, bot_token="1:abc", allowed_user_ids=[owner], owner_id=owner)


def _msg(owner: int = 42) -> Message:
    m = AsyncMock(spec=Message)
    m.from_user = User(id=owner, is_bot=False, first_name="owner")
    m.chat = SimpleNamespace(id=owner)
    m.answer = AsyncMock()
    return m


@pytest.fixture
def client() -> ZarfilmClient:
    return ZarfilmClient(
        _cfg(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>logged in</html>")),
    )


async def test_dashboard_owner_sends_rich_message(client: ZarfilmClient) -> None:
    bot = AsyncMock()
    message = _msg()
    await admin.dashboard(message, bot=bot, cfg=_cfg(), zarfilm=client)  # type: ignore[arg-type]
    bot.send_rich_message.assert_awaited_once()
    rich = bot.send_rich_message.await_args.kwargs["rich_message"]
    table = next(b for b in rich.model_dump(exclude_none=True)["blocks"] if b["type"] == "table")
    flat = [c["text"] for row in table["cells"] for c in row]
    assert any("آنلاین" in t for t in flat)


async def test_dashboard_non_owner_is_ignored(client: ZarfilmClient) -> None:
    bot = AsyncMock()
    message = _msg(owner=999)
    await admin.dashboard(message, bot=bot, cfg=_cfg(), zarfilm=client)  # type: ignore[arg-type]
    bot.send_rich_message.assert_not_awaited()
    message.answer.assert_not_awaited()


async def test_dashboard_refresh_checks_session() -> None:
    bot = AsyncMock()
    message = _msg()
    message.message_id = 7
    zarfilm = AsyncMock()
    zarfilm._restore_session = lambda: True
    zarfilm.session_ttl_seconds = lambda: 3600
    zarfilm.session_valid = AsyncMock(return_value=True)
    cb = AsyncMock()
    cb.from_user = User(id=42, is_bot=False, first_name="owner")
    cb.message = message
    cb.data = "dash:check"
    cb.answer = AsyncMock()
    await admin.dashboard_action(cb, bot=bot, cfg=_cfg(), zarfilm=zarfilm, state=AsyncMock())  # type: ignore[arg-type]
    zarfilm.session_valid.assert_awaited_once()
    bot.edit_message_text.assert_awaited_once()


async def test_session_ttl_parses_wordpress_expiry() -> None:
    import time

    cfg = _cfg()
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    future = int(time.time()) + 86400 * 2
    client.set_cookies({"wordpress_logged_in_x": f"name%7C{future}%7Chash%7Csig"})
    ttl = client.session_ttl_seconds()
    assert ttl is not None and 86400 < ttl <= 86400 * 2 + 5
