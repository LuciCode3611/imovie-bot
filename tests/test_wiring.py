import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.dispatcher.dispatcher import Dispatcher
from aiogram.types import Message

from src.exceptions import ZarfilmError
from src.handlers import card, common
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState


def _config() -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        allowed_user_ids=[42],
    )


def test_build_dispatcher_injects_deps_and_routers() -> None:
    from src.main import build_dispatcher

    dp, zarfilm = build_dispatcher(_config())
    assert isinstance(dp, Dispatcher)
    assert len(dp.sub_routers) == 4
    assert {"cfg", "zarfilm", "cache", "card_state"} <= set(dp.workflow_data)
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
    await card.cancel(cb, card_state=CallbackState(ttl=60))  # type: ignore[arg-type]
    cb.answer.assert_awaited_once_with(card.EXPIRED_TEXT, show_alert=True)


async def test_expired_open_card_key_alerts_with_real_state() -> None:
    cb = AsyncMock()
    cb.data = "m:dead00"
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await card.open_card(  # type: ignore[arg-type]
        cb,
        zarfilm=AsyncMock(),
        cache=AsyncMock(),
        card_state=CallbackState(ttl=60),
        cfg=_config(),
    )
    cb.answer.assert_awaited_once_with(card.EXPIRED_TEXT, show_alert=True)
