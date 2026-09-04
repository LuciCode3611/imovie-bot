import time
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Update, User

from src.exceptions import AuthError, ZarfilmError
from src.handlers import admin, common
from src.models.config import Config, resolve_owner

OWNER_ID = 42
REQUESTER_ID = 7


def _config() -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        owner_id=OWNER_ID,
        allowed_user_ids=[REQUESTER_ID],
    )


def _event(user_id: int) -> SimpleNamespace:
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    return SimpleNamespace(update=SimpleNamespace(message=message, callback_query=None))


def _bot() -> Bot:
    return Bot(token="12345:TEST", session=AsyncMock(spec=BaseSession))


def _message(text: str, user_id: int) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    return message


@pytest.fixture(autouse=True)
def _reset_owner_alert_state() -> Iterator[None]:
    common._owner_alert_state["last"] = float("-inf")
    yield
    common._owner_alert_state["last"] = float("-inf")


@pytest.fixture
def _detach_routers() -> Iterator[None]:
    """aiogram routers allow a single parent dispatcher per process; detach after use
    so build_dispatcher stays callable in other tests."""
    yield
    from src.handlers import admin as admin_module
    from src.handlers import card as card_module
    from src.handlers import search as search_module

    for router in (common.router, search_module.router, card_module.router, admin_module.router):
        router._parent_router = None  # noqa: SLF001 - no public detach API in aiogram


def test_resolve_owner_prefers_owner_id() -> None:
    assert resolve_owner(_config()) == OWNER_ID


def test_resolve_owner_falls_back_to_first_allowed() -> None:
    cfg = Config(_env_file=None, bot_token="1:abc", allowed_user_ids=[9, 3])
    assert resolve_owner(cfg) == 9


def test_resolve_owner_returns_none_without_candidates() -> None:
    cfg = Config(_env_file=None, bot_token="1:abc")
    assert resolve_owner(cfg) is None


async def test_auth_error_not_owner_answers_unavailable_and_dms_owner() -> None:
    cfg = _config()
    bot = _bot()
    bot.send_message = AsyncMock()
    event = _event(REQUESTER_ID)
    handled = await common.on_error(event, AuthError("session expired"), bot=bot, cfg=cfg)
    assert handled is True
    event.update.message.answer.assert_awaited_once_with(common.SERVICE_DOWN_TEXT)
    bot.send_message.assert_awaited_once_with(OWNER_ID, common.SESSION_EXPIRED_TEXT)


async def test_auth_error_owner_answered_session_text_without_dm() -> None:
    cfg = _config()
    bot = _bot()
    bot.send_message = AsyncMock()
    event = _event(OWNER_ID)
    await common.on_error(event, AuthError("session expired"), bot=bot, cfg=cfg)
    event.update.message.answer.assert_awaited_once_with(common.SESSION_EXPIRED_TEXT)
    bot.send_message.assert_not_awaited()


async def test_auth_error_without_resolvable_owner_skips_dm() -> None:
    cfg = Config(_env_file=None, bot_token="1:abc")
    bot = _bot()
    bot.send_message = AsyncMock()
    event = _event(REQUESTER_ID)
    handled = await common.on_error(event, AuthError("session expired"), bot=bot, cfg=cfg)
    assert handled is True
    event.update.message.answer.assert_awaited_once_with(common.SERVICE_DOWN_TEXT)
    bot.send_message.assert_not_awaited()


async def test_auth_error_without_bot_skips_dm() -> None:
    cfg = _config()
    event = _event(REQUESTER_ID)
    handled = await common.on_error(event, AuthError("session expired"), bot=None, cfg=cfg)
    assert handled is True
    event.update.message.answer.assert_awaited_once_with(common.SERVICE_DOWN_TEXT)


async def test_non_auth_zarfilm_error_never_dms_owner() -> None:
    cfg = _config()
    bot = _bot()
    bot.send_message = AsyncMock()
    event = _event(REQUESTER_ID)
    await common.on_error(event, ZarfilmError("parse boom"), bot=bot, cfg=cfg)
    event.update.message.answer.assert_awaited_once_with(common.UNAVAILABLE_TEXT)
    bot.send_message.assert_not_awaited()


async def test_owner_dm_cooldown_suppresses_second_dm() -> None:
    cfg = _config()
    bot = _bot()
    bot.send_message = AsyncMock()
    await common.on_error(_event(REQUESTER_ID), AuthError("session expired"), bot=bot, cfg=cfg)
    await common.on_error(_event(REQUESTER_ID), AuthError("session expired"), bot=bot, cfg=cfg)
    assert bot.send_message.await_count == 1


async def test_owner_dm_resends_after_cooldown_window() -> None:
    cfg = _config()
    bot = _bot()
    bot.send_message = AsyncMock()
    await common.on_error(_event(REQUESTER_ID), AuthError("session expired"), bot=bot, cfg=cfg)
    common._owner_alert_state["last"] -= common._OWNER_ALERT_COOLDOWN + 1.0
    await common.on_error(_event(REQUESTER_ID), AuthError("session expired"), bot=bot, cfg=cfg)
    assert bot.send_message.await_count == 2


async def test_start_login_with_owner_id_and_empty_allowlist() -> None:
    cfg = Config(_env_file=None, bot_token="1:abc", owner_id=OWNER_ID, allowed_user_ids=[])
    fsm = AsyncMock(spec=FSMContext)
    owner = _message("/login", OWNER_ID)
    await admin.start_login(owner, fsm, cfg)
    owner.answer.assert_awaited_once()
    fsm.set_state.assert_awaited_once()

    stranger = _message("/login", REQUESTER_ID)
    await admin.start_login(stranger, AsyncMock(spec=FSMContext), cfg)
    stranger.answer.assert_not_awaited()


@pytest.mark.usefixtures("_detach_routers")
async def test_error_observer_receives_bot_via_aiogram_injection() -> None:
    from src.main import build_dispatcher

    cfg = _config()
    dp, _ = build_dispatcher(cfg)
    captured: dict[str, object] = {}
    async def spy(event: object, exception: Exception | None = None, bot: Bot | None = None, cfg: Config | None = None) -> bool:
        captured["bot"] = bot
        captured["cfg"] = cfg
        captured["exception"] = exception
        return True

    dp.errors.register(spy)
    bot = _bot()

    async def boom(message: Message, **kwargs: object) -> None:
        raise AuthError("session expired")

    dp.message.register(boom)
    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": REQUESTER_ID, "type": "private"},
            "from": {"id": REQUESTER_ID, "is_bot": False, "first_name": "t"},
            "text": "/boom",
        }
    )
    update = Update.model_validate(
        {"update_id": 1, "message": message.model_dump(exclude_none=True)},
        context={"bot": bot},
    )
    await dp.feed_update(bot, update)
    assert captured["bot"] is bot
    assert captured["cfg"] is cfg


def test_owner_alert_texts_are_source_neutral() -> None:
    assert "/login" in common.SESSION_EXPIRED_TEXT
    assert "zarfilm" not in common.SESSION_EXPIRED_TEXT.lower()


def test_cooldown_constant_is_ten_minutes() -> None:
    assert common._OWNER_ALERT_COOLDOWN == 600.0
    assert time.monotonic() >= 0.0
