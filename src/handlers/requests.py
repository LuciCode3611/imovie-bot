"""User content-request flow.

When a search yields nothing (or a card has no download links) the user gets
a «📥 ثبت درخواست» button. A single tap registers the request in the SQLite
queue and edits the message in place to «درخواست شما ثبت شد ✅».
"""

import contextlib
from html import escape

from aiogram import F, Router
from aiogram.enums.button_style import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from src.repos.db import Database
from src.repos.state import CallbackState

router = Router(name="requests")

NO_TITLE_TEXT = "عنوانی برای ثبت پیدا نشد؛ دوباره جستجو کن."


def request_prompt_keyboard() -> InlineKeyboardMarkup:
    """Button under a failed search; the failed query travels via FSM data."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 ثبت درخواست", callback_data="req:go", style=ButtonStyle.PRIMARY)]
        ]
    )


def card_request_keyboard(key: str) -> InlineKeyboardMarkup:
    """Button on a detail card with no downloadable links."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 ثبت درخواست", callback_data=f"req:c:{key}", style=ButtonStyle.PRIMARY)]
        ]
    )


def no_request_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])


async def _confirm(callback: CallbackQuery, title: str, db: Database, state: FSMContext | None = None) -> None:
    user = callback.from_user
    db.add_request(
        user_id=user.id if user else 0,
        user_name=user.full_name if user else "ناشناس",
        title=title,
    )
    if state is not None:
        with contextlib.suppress(Exception):
            await state.update_data(req_query=None)
    # clear the button first, then turn the message into the confirmation —
    # both suppressed so a rich/photo message still answers the callback
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(f"✅ درخواست «{escape(title[:80])}» ثبت شد؛ به‌زودی بررسیش می‌کنیم. 🎬")
    await callback.answer("درخواست شما ثبت شد ✅")


@router.callback_query(F.data == "req:go")
async def request_from_search(
    callback: CallbackQuery,
    db: Database,
    state: FSMContext,
) -> None:
    # the search handler stored the failed query in FSM data
    data = await state.get_data()
    query = (data or {}).get("req_query")
    if not query:
        await callback.answer(NO_TITLE_TEXT, show_alert=True)
        return
    await _confirm(callback, str(query), db, state)


@router.callback_query(F.data.startswith("req:c:"))
async def request_from_card(callback: CallbackQuery, db: Database, card_state: CallbackState) -> None:
    key = (callback.data or "").removeprefix("req:c:")
    entry = card_state.get(key)
    if entry is None or not entry.details:
        await callback.answer("عنوان در دسترس نیست؛ دوباره جستجو کن.", show_alert=True)
        return
    title = entry.details.summary.title_en
    await _confirm(callback, title, db)
