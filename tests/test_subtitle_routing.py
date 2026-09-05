"""Dispatcher-level routing for the subtitle flow: the «📝 جستجوی زیرنویس»
button / ``/subtitle`` arm a separate listening state, free text outside any
state still gets the movie-search hint, both searches never collide — and the
whole SubDL flow (search → card → public zip buttons) works end to end."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, SendMessage, SendRichMessage
from aiogram.types import Message, Update

from src.handlers import search, subtitle_search
from src.models import MovieSummary, SubtitleSummary
from src.models.config import Config
from src.services.subdl import SubdlClient

OWNER_ID = 42


class _StubZarfilm:
    def __init__(self) -> None:
        self.search_calls: list[str] = []

    async def search(self, query: str) -> list[MovieSummary]:
        self.search_calls.append(query)
        return []


class _StubSubdl:
    enabled = True  # a host with SUBDL_API_KEY set

    def __init__(self) -> None:
        self.search_calls: list[str] = []

    async def search(self, query: str) -> list[SubtitleSummary]:
        self.search_calls.append(query)
        return [SubtitleSummary(title_en=f"Hit {i}", sd_id=f"{900 + i}", year=2020) for i in range(7)]

    async def close(self) -> None:
        return None


@pytest.fixture
def _detach_routers() -> Iterator[None]:
    yield
    from src.handlers import admin as admin_module
    from src.handlers import card as card_module
    from src.handlers import common as common_module
    from src.handlers import requests as requests_module
    from src.handlers import search as search_module
    from src.handlers import subtitle_card as subtitle_card_module
    from src.handlers import subtitle_search as subtitle_search_module

    for router in (
        common_module.router,
        requests_module.router,
        search_module.router,
        card_module.router,
        admin_module.router,
        subtitle_search_module.router,
        subtitle_card_module.router,
    ):
        router._parent_router = None


def _message_update(text: str, update_id: int, bot: Bot) -> Update:
    message = Message.model_validate(
        {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": OWNER_ID, "type": "private"},
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "t"},
            "text": text,
        }
    )
    return Update.model_validate({"update_id": update_id, "message": message.model_dump(exclude_none=True)}, context={"bot": bot})


def _callback_update(update_id: int, bot: Bot, data: str) -> Update:
    message = Message.model_validate(
        {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": OWNER_ID, "type": "private"},
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "t"},
            "text": "old",
        }
    )
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": str(update_id),
                "from": {"id": OWNER_ID, "is_bot": False, "first_name": "t"},
                "chat_instance": "ci",
                "data": data,
                "message": message.model_dump(exclude_none=True),
            },
        },
        context={"bot": bot},
    )


def _build(tmp_path: Path):
    from src.main import build_dispatcher

    cfg = Config(
        _env_file=None,
        bot_token="1:abc",
        owner_id=OWNER_ID,
        allowed_user_ids=[OWNER_ID],
        session_path=tmp_path / "session.json",
        db_path=tmp_path / "bot.db",
    )
    dp, _ = build_dispatcher(cfg)
    zarfilm, subdl = _StubZarfilm(), _StubSubdl()
    dp.workflow_data["zarfilm"] = zarfilm
    dp.workflow_data["subdl"] = subdl
    sent: list = []
    session = AsyncMock(spec=BaseSession)

    async def call(bot: Bot, method, timeout=None):
        sent.append(method)
        if isinstance(method, (SendMessage, SendRichMessage)):
            return Message.model_validate(
                {"message_id": 1000 + len(sent), "date": 0, "chat": {"id": OWNER_ID, "type": "private"}, "text": getattr(method, "text", None)},
                context={"bot": bot},
            )
        return True

    session.side_effect = call
    bot = Bot(token="12345:TEST", session=session)
    return dp, bot, zarfilm, subdl, sent


@pytest.mark.usefixtures("_detach_routers")
async def test_subtitle_button_routes_text_to_subdl_not_zarfilm(tmp_path: Path) -> None:
    dp, bot, zarfilm, subdl, sent = _build(tmp_path)

    await dp.feed_update(bot, _message_update("dune", 1, bot))
    assert zarfilm.search_calls == [] and subdl.search_calls == []
    assert [m.text for m in sent if isinstance(m, SendMessage)][-1] == search.HINT_TEXT

    await dp.feed_update(bot, _callback_update(2, bot, "srch:sub_go"))
    assert [m.text for m in sent if isinstance(m, EditMessageText)][-1] == subtitle_search.LISTENING_TEXT
    await dp.feed_update(bot, _message_update("dune", 3, bot))
    assert subdl.search_calls == ["dune"] and zarfilm.search_calls == []

    header_edit = [m for m in sent if isinstance(m, EditMessageText)][-1]
    assert header_edit.text == "زیرنویس‌های «dune» — نمایش 1–5 از 7:"
    rows = header_edit.reply_markup.inline_keyboard
    assert rows[0][0].callback_data.startswith("sm:")
    assert [b.text for b in rows[-1]] == ["1/2", "▶"]

    # pagination callback is served by the subtitle router (spg:), not pg:
    await dp.feed_update(bot, _callback_update(4, bot, rows[-1][1].callback_data))
    page_edit = [m for m in sent if isinstance(m, EditMessageText)][-1]
    assert page_edit.text == "زیرنویس‌های «dune» — نمایش 6–7 از 7:"
    assert [b.text for b in page_edit.reply_markup.inline_keyboard[-1]] == ["◀", "2/2"]

    # the listening state is cleared after results: plain text is a hint again
    await dp.feed_update(bot, _message_update("dune", 5, bot))
    assert subdl.search_calls == ["dune"]


@pytest.mark.usefixtures("_detach_routers")
async def test_subtitle_command_and_movie_search_stay_independent(tmp_path: Path) -> None:
    dp, bot, zarfilm, subdl, sent = _build(tmp_path)

    await dp.feed_update(bot, _message_update("/subtitle", 1, bot))
    assert [m.text for m in sent if isinstance(m, SendMessage)][-1] == subtitle_search.LISTENING_TEXT
    await dp.feed_update(bot, _message_update("lanterns", 2, bot))
    assert subdl.search_calls == ["lanterns"] and zarfilm.search_calls == []

    await dp.feed_update(bot, _message_update("/search", 3, bot))
    await dp.feed_update(bot, _message_update("lanterns", 4, bot))
    assert zarfilm.search_calls == ["lanterns"] and subdl.search_calls == ["lanterns"]

    # /start resets the subtitle listening state too
    await dp.feed_update(bot, _message_update("/subtitle", 5, bot))
    await dp.feed_update(bot, _message_update("/start", 6, bot))
    await dp.feed_update(bot, _message_update("lanterns", 7, bot))
    assert subdl.search_calls == ["lanterns"]
    welcome = [m for m in sent if isinstance(m, SendMessage) and m.reply_markup is not None and "سلام" in m.text][-1]
    assert [b.callback_data for b in welcome.reply_markup.inline_keyboard[0]] == ["srch:go", "srch:sub_go"]


SEARCH_ANSWER = {
    "status": True,
    "results": [
        {"name": "Interstellar", "sd_id": 1, "type": "movie", "year": 2014, "imdb_id": "tt0816692"},
        {"name": "Dark", "sd_id": 2, "type": "tv", "year": 2017},
    ],
    "subtitles": [{"release_name": "Interstellar.2014.1080p.BluRay", "url": "/subtitle/11-22.zip", "language": "FA"}],
}
TITLE_ANSWER = {
    "status": True,
    "results": [{"name": "Interstellar", "sd_id": 1, "type": "movie", "year": 2014}],
    "subtitles": [
        {"release_name": "Interstellar.2014.1080p.BluRay", "url": "/subtitle/11-22.zip", "language": "FA"},
        {"release_name": "Interstellar.2014.English", "url": "/subtitle/33-44.zip", "language": "EN"},
        # an authenticated link must never reach a button
        {"release_name": "Interstellar.2014.WEB-DL", "url": "https://dl.subdl.com/subtitle/55-66.zip?api_key=leaked-key", "language": "FA"},
    ],
}


@pytest.mark.usefixtures("_detach_routers")
async def test_subtitle_flow_end_to_end_against_a_mocked_subdl_api(tmp_path: Path) -> None:
    """Search → results → card → public zip buttons, through the real client and parsers."""
    dp, bot, _zarfilm, _stub, sent = _build(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        answer = SEARCH_ANSWER if "film_name" in request.url.params else TITLE_ANSWER
        return httpx.Response(200, json=answer)

    client = SubdlClient(Config(_env_file=None, bot_token="1:abc", subdl_api_key="k"), transport=httpx.MockTransport(handler))
    dp.workflow_data["subdl"] = client
    try:
        await dp.feed_update(bot, _callback_update(1, bot, "srch:sub_go"))
        await dp.feed_update(bot, _message_update("interstellar", 2, bot))

        header = [m for m in sent if isinstance(m, EditMessageText)][-1]
        assert header.text == "زیرنویس‌های «interstellar»:"
        assert [b.text for row in header.reply_markup.inline_keyboard[:2] for b in row] == ["🎬 Interstellar (2014)", "📺 Dark (2017)"]
        first = header.reply_markup.inline_keyboard[0][0].callback_data

        await dp.feed_update(bot, _callback_update(3, bot, first))
        rich = [m for m in sent if isinstance(m, SendRichMessage)][-1]
        buttons = [b for row in rich.reply_markup.inline_keyboard for b in row]
        # only the two Persian files, both public zips, and no key anywhere in the card
        assert [b.url for b in buttons] == ["https://dl.subdl.com/subtitle/11-22.zip", "https://dl.subdl.com/subtitle/55-66.zip"]
        card = rich.reply_markup.model_dump_json() + rich.rich_message.model_dump_json()
        assert "leaked-key" not in card and "api_key" not in card
        assert buttons[0].text == "دانلود Interstellar.2014.1080p.BluRay"
        table = rich.rich_message.blocks[0]
        assert table.cells[0][0].text == "Interstellar (2014)"
    finally:
        await client.close()

    assert [dict(r.url.params)["languages"] for r in requests] == ["FA", "FA"]
    assert all(r.url.params["api_key"] == "k" for r in requests)
    assert dict(requests[0].url.params)["film_name"] == "interstellar"
    assert dict(requests[1].url.params)["sd_id"] == "1"
