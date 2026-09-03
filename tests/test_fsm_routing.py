import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Message, Update

from src.handlers import search
from src.models import MovieSummary
from src.models.config import Config

OWNER_ID = 42
COOKIE_PASTE = "wordpress_logged_in_x=abc; theme=dark"


class _StubZarfilm:
    def __init__(self) -> None:
        self._client = httpx.Client()
        self.ready = False
        self.search_calls: list[str] = []

    def mark_session_ready(self) -> None:
        self.ready = True

    async def search(self, query: str) -> list[MovieSummary]:
        self.search_calls.append(query)
        return []


@pytest.fixture
def _detach_routers() -> Iterator[None]:
    """aiogram routers allow a single parent dispatcher per process; detach after use
    so build_dispatcher stays callable in other tests."""
    yield
    from src.handlers import admin as admin_module
    from src.handlers import card as card_module
    from src.handlers import common as common_module
    from src.handlers import search as search_module

    for router in (
        common_module.router,
        search_module.router,
        card_module.router,
        admin_module.router,
    ):
        router._parent_router = None  # noqa: SLF001 - no public detach API in aiogram


def _update(text: str, update_id: int, bot: Bot) -> Update:
    message = Message.model_validate(
        {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": OWNER_ID, "type": "private"},
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "t"},
            "text": text,
        }
    )
    return Update.model_validate(
        {"update_id": update_id, "message": message.model_dump(exclude_none=True)},
        context={"bot": bot},
    )


def _answered_texts(session: AsyncMock) -> list[str]:
    texts: list[str] = []
    for call in session.call_args_list:
        method = call.args[1] if len(call.args) >= 2 else None
        if isinstance(method, SendMessage):
            texts.append(method.text)
    return texts


@pytest.mark.usefixtures("_detach_routers")
async def test_cookie_paste_reaches_admin_fsm_not_search(tmp_path: Path) -> None:
    from src.main import build_dispatcher

    cfg = Config(
        _env_file=None,
        bot_token="1:abc",
        owner_id=OWNER_ID,
        allowed_user_ids=[OWNER_ID],
        session_path=tmp_path / "session.json",
    )
    dp, _ = build_dispatcher(cfg)
    stub = _StubZarfilm()
    dp.workflow_data["zarfilm"] = stub
    session = AsyncMock(spec=BaseSession)
    bot = Bot(token="12345:TEST", session=session)

    await dp.feed_update(bot, _update("/login", 1, bot))
    await dp.feed_update(bot, _update(COOKIE_PASTE, 2, bot))

    assert stub.search_calls == []
    saved = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert saved["wordpress_logged_in_x"] == "abc"
    texts = _answered_texts(session)
    assert search.NO_RESULTS_TEXT not in texts
    assert texts and texts[-1].endswith("به‌روزرسانی شد.")
