import logging
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.dispatcher.dispatcher import Dispatcher
from aiogram.types import Message, User

from src.exceptions import ZarfilmError
from src.handlers import card, common
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState


@pytest.fixture
def _detach_routers() -> Iterator[None]:
    """aiogram routers allow a single parent dispatcher per process; detach after use
    so build_dispatcher stays callable in other tests."""
    yield
    from src.handlers import admin as admin_module
    from src.handlers import card as card_module
    from src.handlers import common as common_module
    from src.handlers import requests as requests_module
    from src.handlers import search as search_module

    for router in (
        common_module.router,
        requests_module.router,
        search_module.router,
        card_module.router,
        admin_module.router,
    ):
        router._parent_router = None  # noqa: SLF001 - no public detach API in aiogram


def _config() -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        allowed_user_ids=[42],
    )


@pytest.mark.usefixtures("_detach_routers")
def test_build_dispatcher_injects_deps_and_routers() -> None:
    from src.main import build_dispatcher

    dp, zarfilm = build_dispatcher(_config())
    assert isinstance(dp, Dispatcher)
    assert len(dp.sub_routers) == 5
    assert {"cfg", "zarfilm", "cache", "card_state", "db"} <= set(dp.workflow_data)
    assert dp.workflow_data["cfg"] is not None
    assert dp.workflow_data["zarfilm"] is zarfilm
    assert isinstance(dp.workflow_data["cache"], TTLCache)
    assert isinstance(dp.workflow_data["card_state"], CallbackState)
    assert "state" not in dp.workflow_data


async def test_on_error_warns_and_answers_message(caplog: pytest.LogCaptureFixture) -> None:
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    event = SimpleNamespace(update=SimpleNamespace(message=message, callback_query=None))
    with caplog.at_level(logging.WARNING):
        handled = await common.on_error(event, ZarfilmError("boom"))  # type: ignore[arg-type]
    assert handled is True
    message.answer.assert_awaited_once_with(common.UNAVAILABLE_TEXT)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_expired_cancel_key_alerts_with_real_state() -> None:
    cb = AsyncMock()
    cb.data = "x:dead00"
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await card.cancel(cb, bot=AsyncMock(), card_state=CallbackState(ttl=60), cfg=_config())  # type: ignore[arg-type]
    cb.answer.assert_awaited_once_with(card.EXPIRED_TEXT, show_alert=True)


async def test_expired_open_card_key_alerts_with_real_state() -> None:
    cb = AsyncMock()
    cb.data = "m:dead00"
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await card.open_card(  # type: ignore[arg-type]
        cb,
        bot=AsyncMock(),
        zarfilm=AsyncMock(),
        cache=AsyncMock(),
        card_state=CallbackState(ttl=60),
        cfg=_config(),
    )
    cb.answer.assert_awaited_once_with(card.EXPIRED_TEXT, show_alert=True)


async def test_start_clears_state_and_attaches_search_button() -> None:
    message = AsyncMock(spec=Message)
    message.from_user = User(id=42, is_bot=False, first_name="owner")
    message.answer = AsyncMock()
    state = AsyncMock()
    await common.start(message, state, cfg=_config())  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "srch:go"
    state.clear.assert_awaited_once()


async def test_start_greets_user_by_name_without_dashboard_hint() -> None:
    message = AsyncMock(spec=Message)
    message.from_user = User(id=99, is_bot=False, first_name="رضا", last_name="احمدی")
    message.answer = AsyncMock()
    await common.start(message, AsyncMock(), cfg=_config())  # type: ignore[arg-type]
    text = message.answer.await_args.args[0]
    assert "رضا احمدی" in text
    assert "/status" not in text  # the owner dashboard hint must never appear
    assert "راهنمای سریع" in text
    assert '<tg-emoji emoji-id="5440660757194744323">' in text
    assert '<tg-emoji emoji-id="5325547803936572038">' in text
    assert '<tg-emoji emoji-id="5467538555158943525">' in text
    assert "<blockquote>" in text
    assert message.answer.await_args.kwargs["parse_mode"] == "HTML"


async def test_on_error_notfound_answers_specific_text() -> None:
    from src.exceptions import NotFoundError

    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    event = SimpleNamespace(update=SimpleNamespace(message=message, callback_query=None))
    handled = await common.on_error(event, NotFoundError("gone"), bot=None, cfg=_config())  # type: ignore[arg-type]
    assert handled is True
    message.answer.assert_awaited_once_with(common.NOT_FOUND_TEXT)


@pytest.mark.usefixtures("_detach_routers")
async def test_build_dispatcher_warns_on_empty_allowlist_and_missing_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.main import build_dispatcher

    cfg = Config(_env_file=None, bot_token="1:abc", allowed_user_ids=[])
    with caplog.at_level(logging.INFO):
        _, zarfilm = build_dispatcher(cfg)
        await zarfilm.close()
    assert any("OPEN TO EVERY user" in record.message for record in caplog.records)
    assert any("no owner configured" in record.message for record in caplog.records)
