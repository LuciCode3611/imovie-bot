"""User content-request flow: one tap on «ثبت درخواست» saves + confirms."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from src.handlers import requests as req
from src.models import MediaKind, MovieDetails, MovieSummary
from src.repos.db import Database
from src.repos.state import CallbackState, CardEntry


def _cb(data: str) -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.message = AsyncMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.answer = AsyncMock()
    cb.from_user = User(id=7, is_bot=False, first_name="کاربر")
    return cb


def _fsm(data: dict | None = None) -> FSMContext:
    state = AsyncMock(spec=FSMContext)
    store: dict = dict(data or {})

    async def get_data() -> dict:
        return dict(store)

    async def update_data(**kwargs: object) -> None:
        store.update(kwargs)

    state.get_data = get_data
    state.update_data = update_data
    return state


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "req.db")


async def test_search_request_button_registers_query_and_edits_message(db: Database) -> None:
    state = _fsm({"req_query": "Black Torch"})
    cb = _cb("req:go")
    await req.request_from_search(cb, db=db, state=state)
    assert db.count_open_requests() == 1
    row = db.list_requests()[0]
    assert row.title == "Black Torch"
    assert row.user_id == 7
    # the message turns into the confirmation and the button is removed
    cb.message.edit_text.assert_awaited_once()
    assert "ثبت شد" in cb.message.edit_text.await_args.args[0]
    cb.message.edit_reply_markup.assert_awaited_once()
    cb.answer.assert_awaited_once()
    assert "ثبت شد" in cb.answer.await_args.args[0]


async def test_search_request_without_query_alerts(db: Database) -> None:
    state = _fsm({})
    cb = _cb("req:go")
    await req.request_from_search(cb, db=db, state=state)
    assert db.count_open_requests() == 0
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_card_request_button_registers_title(db: Database) -> None:
    details = MovieDetails(summary=MovieSummary(slug="black-torch", title_en="Black Torch", kind=MediaKind.SERIES))
    entry = CardEntry(summary=details.summary, details=details)
    card_state = CallbackState(ttl=60)
    key = card_state.create(entry)
    cb = _cb(f"req:c:{key}")
    await req.request_from_card(cb, db=db, card_state=card_state)
    assert db.count_open_requests() == 1
    assert db.list_requests()[0].title == "Black Torch"


async def test_card_request_unknown_key_alerts(db: Database) -> None:
    cb = _cb("req:c:nope")
    await req.request_from_card(cb, db=db, card_state=CallbackState(ttl=60))
    assert db.count_open_requests() == 0
    cb.answer.assert_awaited_once()
