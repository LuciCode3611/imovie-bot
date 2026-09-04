"""User content-request flow: FSM prompt -> saved request."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from src.handlers import requests as req
from src.repos.db import Database


def _msg(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.chat = SimpleNamespace(id=1)
    message.from_user = User(id=user_id, is_bot=False, first_name="t", last_name="کاربر")
    message.answer = AsyncMock()
    return message


def _cb(data: str = "req:start") -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.message = AsyncMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    cb.from_user = User(id=42, is_bot=False, first_name="t")
    return cb


def _state() -> FSMContext:
    state = AsyncMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.update_data = AsyncMock()
    return state


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "req.db")


async def test_request_start_enters_state(db: Database) -> None:
    state = _state()
    await req.start_request(_cb(), state)
    state.set_state.assert_awaited_once()
    cb = _cb()
    cb.answer.assert_not_called()


async def test_request_cancel_clears_state(db: Database) -> None:
    state = _state()
    await req.cancel_request(_cb("req:cancel"), state)
    state.clear.assert_awaited_once()


async def test_request_title_is_saved(db: Database) -> None:
    state = _state()
    message = _msg("The Last of Us فصل ۳")
    await req.receive_request(message, state, db)
    assert db.count_open_requests() == 1
    row = db.list_requests()[0]
    assert row.title == "The Last of Us فصل ۳"
    assert row.user_id == 42
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert "ثبت" in message.answer.await_args.args[0]


async def test_short_title_reprompts(db: Database) -> None:
    state = _state()
    message = _msg("x")
    await req.receive_request(message, state, db)
    assert db.count_open_requests() == 0
    state.clear.assert_not_awaited()
