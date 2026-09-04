"""Owner dashboard overview + user/request management views."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Message, User

from src.handlers import admin, admin_views
from src.models.config import Config
from src.repos.db import Database


def _cfg() -> Config:
    return Config(_env_file=None, bot_token="1:abc", owner_id=42, allowed_user_ids=[42])


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "admin.db")
    database.upsert_user(42, "owner", None)
    database.upsert_user(7, "کاربر مهمان", "guest")
    database.increment_searches(7)
    database.add_request(7, "کاربر مهمان", "Silo")
    return database


def _cb(data: str) -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.from_user = User(id=42, is_bot=False, first_name="owner")
    cb.message = AsyncMock(spec=Message)
    cb.message.chat = SimpleNamespace(id=1)
    cb.message.message_id = 9
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def test_overview_rich_includes_user_and_request_stats(db: Database) -> None:
    stats = {
        "online": True,
        "session_present": True,
        "session_valid": True,
        "ttl_human": "۱ روز",
        "uptime_human": "۲ ساعت",
        "open_mode": True,
        "proxy": None,
        "users": db.count_users(),
        "active_7d": 2,
        "blocked": 0,
        "searches": 1,
        "searches_total": 1,
        "movies": 3,
        "requests_open": 1,
        "requests_total": 1,
    }
    rich = admin_views.overview_rich(stats)
    tables = [b for b in rich.blocks if getattr(b, "cells", None)]
    flat = [c for block in tables for row in block.cells for c in row]
    texts = [c.text if isinstance(c.text, str) else "" for c in flat]
    assert any("کاربران" in t for t in texts)
    assert any("درخواست" in t for t in texts)
    # keyboard offers the two management sections
    kb = admin_views.overview_keyboard()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "adm:users:0" in callbacks and "adm:reqs:0" in callbacks


async def test_users_view_lists_and_blocks(db: Database) -> None:
    bot = AsyncMock()
    await admin.admin_manage(_cb("adm:users:0"), bot=bot, cfg=_cfg(), db=db)
    bot.edit_message_text.assert_awaited_once()
    kw = bot.edit_message_text.await_args.kwargs
    markup = kw["reply_markup"]
    flat = [btn for row in markup.inline_keyboard for btn in row]
    assert any(str(btn.callback_data or "").startswith("adm:blk:7") for btn in flat)

    # block user 7
    bot.edit_message_text = AsyncMock()
    await admin.admin_manage(_cb("adm:blk:7"), bot=bot, cfg=_cfg(), db=db)
    assert db.is_blocked(7) is True
    # owner can never be blocked through the panel
    await admin.admin_manage(_cb("adm:blk:42"), bot=bot, cfg=_cfg(), db=db)
    assert db.is_blocked(42) is False


async def test_requests_view_marks_done(db: Database) -> None:
    bot = AsyncMock()
    await admin.admin_manage(_cb("adm:reqs:0"), bot=bot, cfg=_cfg(), db=db)
    markup = bot.edit_message_text.await_args.kwargs["reply_markup"]
    flat = [btn for row in markup.inline_keyboard for btn in row]
    rid = db.list_requests("open")[0].id
    assert any((btn.callback_data or "") == f"adm:rdone:{rid}" for btn in flat)
    bot.edit_message_text = AsyncMock()
    await admin.admin_manage(_cb(f"adm:rdone:{rid}"), bot=bot, cfg=_cfg(), db=db)
    assert db.count_open_requests() == 0


async def test_admin_manage_rejects_non_owner(db: Database) -> None:
    cb = _cb("adm:users:0")
    cb.from_user = User(id=999, is_bot=False, first_name="stranger")
    bot = AsyncMock()
    await admin.admin_manage(cb, bot=bot, cfg=_cfg(), db=db)
    bot.edit_message_text.assert_not_awaited()
    cb.answer.assert_awaited_once()
