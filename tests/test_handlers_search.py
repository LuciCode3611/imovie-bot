from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message, User

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
    message.answer = AsyncMock()
    return message


@pytest.fixture
def deps() -> dict[str, object]:
    return {
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc", zarfilm_username="u", zarfilm_password="p"),
    }


async def test_search_replies_with_result_buttons(deps: dict[str, object]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results())
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    kb = kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data.startswith("m:")


async def test_search_no_results_message(deps: dict[str, object]) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=[])
    message = _message("qqqqqq")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    text = message.answer.await_args.args[0]
    assert "پیدا نشد" in text


async def test_search_uses_cache_before_site(deps: dict[str, object]) -> None:
    await deps["cache"].set("search:interstellar", _results(), ttl=60)
    deps["zarfilm"].search = AsyncMock()
    message = _message("interstellar")
    await search.handle_search(message, **deps)  # type: ignore[arg-type]
    deps["zarfilm"].search.assert_not_awaited()
