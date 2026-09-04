from pathlib import Path
from types import SimpleNamespace
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
from src.repos.state import CallbackState, CardEntry, SearchEntry


def _results() -> list[MovieSummary]:
    return [MovieSummary(slug="interstellar-2014", title_en="Interstellar", year=2014)]


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.chat = SimpleNamespace(id=user_id)
    message.answer = AsyncMock(return_value=AsyncMock())
    return message


def _state() -> FSMContext:
    state = AsyncMock(spec=FSMContext)
    state.clear = AsyncMock()
    return state


@pytest.fixture
def deps(tmp_path: Path) -> dict[str, Any]:
    from src.repos.db import Database

    return {
        "bot": AsyncMock(),
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc"),
        "state": _state(),
        "db": Database(tmp_path / "test.db"),
    }


async def test_search_replies_with_result_buttons(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results())
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    sent = message.answer.await_args
    assert search.SEARCHING_TEXT in sent.args[0] and search.SEARCHING_EMOJI_ID in sent.args[0]
    assert sent.kwargs.get("parse_mode") == "HTML"
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


async def test_search_threads_custom_emoji_map(tmp_path: Path) -> None:
    from src.repos.db import Database

    deps_local: dict[str, Any] = {
        "bot": AsyncMock(),
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(search=AsyncMock(return_value=_results())),
        "cfg": Config(_env_file=None, bot_token="1:abc", emoji={"result": "555"}),
        "state": _state(),
        "db": Database(tmp_path / "test.db"),
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
    # no-results notice + the request prompt
    assert message.answer.await_count == 2
    deps["state"].clear.assert_awaited_once()
    deps["state"].set_state.assert_awaited_once()
    # the request is recorded when the user sends the title
    assert deps["db"].count_open_requests() == 0


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
    await search.search_hint(message, cfg=Config(_env_file=None, bot_token="1:abc"))  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "srch:go"


def _results_page(n: int) -> list:
    return [MovieSummary(slug=f"m{i}-2014", title_en=f"Movie {i}", year=2014) for i in range(n)]


async def test_search_paginates_long_result_lists(deps: dict[str, Any]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results_page(7))
    message = _message("q")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    header = status.edit_text.await_args.args[0]
    assert "نمایش 1–5 از 7" in header
    kb = status.edit_text.await_args.kwargs["reply_markup"]
    nav = kb.inline_keyboard[-1]
    assert [b.text for b in nav] == ["1/2", "▶"]
    assert nav[1].callback_data.startswith("pg:")


async def test_change_page_edits_header_and_keyboard(deps: dict[str, Any]) -> None:
    pairs = []
    for summary in _results_page(7):
        entry = CardEntry(summary=summary)
        pairs.append((deps["card_state"].create(entry), entry))
    skey = deps["card_state"].create_search(SearchEntry(query="q", pairs=pairs))

    callback = _callback(f"pg:{skey}:1")
    await search.change_page(callback, card_state=deps["card_state"], cfg=deps["cfg"])  # type: ignore[arg-type]
    callback.message.edit_text.assert_awaited_once()
    header = callback.message.edit_text.await_args.args[0]
    assert "نمایش 6–7 از 7" in header
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert [b.text for b in kb.inline_keyboard[-1]] == ["◀", "2/2"]
    first_title = kb.inline_keyboard[0][0].text
    assert "Movie 5" in first_title


async def test_change_page_expired_key_alerts() -> None:
    callback = _callback("pg:dead00:1")
    await search.change_page(callback, card_state=CallbackState(ttl=60), cfg=Config(_env_file=None, bot_token="1:abc"))  # type: ignore[arg-type]
    callback.answer.assert_awaited_once()
    assert "منقضی" in callback.answer.await_args.args[0]


async def test_change_page_indicator_and_out_of_range_answer_silently() -> None:
    state = CallbackState(ttl=60)
    entry = CardEntry(summary=_results_page(1)[0])
    skey = state.create_search(SearchEntry(query="q", pairs=[(state.create(entry), entry)]))
    for data in (f"pg:{skey}:i", f"pg:{skey}:9", f"pg:{skey}:x"):
        callback = _callback(data)
        await search.change_page(callback, card_state=state, cfg=Config(_env_file=None, bot_token="1:abc"))  # type: ignore[arg-type]
        callback.answer.assert_awaited_once_with()
        callback.message.edit_text.assert_not_awaited()
