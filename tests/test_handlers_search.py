from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Message, User

from src.handlers import search
from src.models import MovieSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState


def _results() -> list[MovieSummary]:
    return [MovieSummary(slug="interstellar-2014", title_en="Interstellar", year=2014)]


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock(return_value=AsyncMock())
    return message


def _state() -> FSMContext:
    state = AsyncMock(spec=FSMContext)
    state.clear = AsyncMock()
    return state


@pytest.fixture
def deps() -> dict[str, Any]:
    return {
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc"),
        "state": _state(),
    }


async def test_search_replies_with_result_buttons(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results())
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    assert message.answer.await_args.args[0] == search.SEARCHING_TEXT
    status.edit_text.assert_awaited_once()
    kb = status.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data.startswith("m:")
    assert kb.inline_keyboard[0][0].text.startswith("🎬")


async def test_cached_search_skips_loading_message(deps: dict[str, Any]) -> None:
    await deps["cache"].set("search:interstellar", _results(), ttl=60)
    deps["zarfilm"].search = AsyncMock()
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0].startswith("نتایج برای")
    message.answer.return_value.edit_text.assert_not_awaited()


async def test_search_threads_custom_emoji_map(tmp_path) -> None:
    deps_local: dict[str, Any] = {
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(search=AsyncMock(return_value=_results())),
        "cfg": Config(_env_file=None, bot_token="1:abc", emoji={"result": "555"}),
        "state": _state(),
    }
    message = _message("interstellar")
    await search.handle_search(message, **deps_local)  # type: ignore[arg-type]
    kb = message.answer.return_value.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].icon_custom_emoji_id == "555"


async def test_search_no_results_message(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=[])
    message = _message("qqqqqq")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    status.edit_text.assert_awaited_once_with(search.NO_RESULTS_TEXT)


async def test_search_uses_cache_before_site(deps: dict[str, Any]) -> None:
    await deps["cache"].set("search:interstellar", _results(), ttl=60)
    deps["zarfilm"].search = AsyncMock()
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    deps["zarfilm"].search.assert_not_awaited()


async def test_state_cleared_after_results(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results())
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    deps["state"].clear.assert_awaited_once()


async def test_state_cleared_after_no_results(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=[])
    message = _message("qqqqqq")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    deps["state"].clear.assert_awaited_once()


def _callback(data: str) -> CallbackQuery:
    callback = AsyncMock(spec=CallbackQuery)
    callback.data = data
    callback.message = AsyncMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_begin_search_sets_listening_state() -> None:
    state = _state()
    callback = _callback("srch:go")
    await search.begin_search(callback, state)  # type: ignore[arg-type]
    state.set_state.assert_awaited_once_with(search.SearchStates.listening)
    callback.message.edit_text.assert_awaited_once_with(search.LISTENING_TEXT)
    callback.answer.assert_awaited_once()


async def test_begin_search_swallows_not_modified() -> None:
    state = _state()
    callback = _callback("srch:go")
    callback.message.edit_text.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"), message="Bad Request: message is not modified"
    )
    await search.begin_search(callback, state)  # type: ignore[arg-type]
    callback.answer.assert_awaited_once()


async def test_free_text_hint_carries_search_button() -> None:
    message = _message("سلام")
    await search.search_hint(message)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "srch:go"
