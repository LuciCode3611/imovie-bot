"""User content-request flow.

When a search yields nothing (or a card has no download links) the user gets
a «📥 درخواست این عنوان» button. Tapping it asks for the title; the first
plain-text message is stored in the SQLite requests queue for the owner to
review from the dashboard.
"""

import contextlib

from aiogram import F, Router
from aiogram.enums.button_style import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.repos.db import Database

router = Router(name="requests")

ASK_REQUEST_TEXT = "📥 اسم فیلم یا سریالی که می‌خوای رو بنویس تا برامون ثبت بشه.\nبرای لغو، /start رو بزن یا دکمهٔ زیر رو بزن."
REQUEST_SAVED_TEXT = "✅ درخواستت ثبت شد؛ به‌زودی بررسیش می‌کنیم. ممنون! 🎬"
CANCELLED_TEXT = "درخواست لغو شد."
TITLE_TOO_SHORT_TEXT = "اسم رو واضح‌تر بنویس (حداقل ۲ حرف)."

MAX_TITLE_LEN = 200


class RequestStates(StatesGroup):
    title = State()


def request_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 درخواست این عنوان", callback_data="req:start", style=ButtonStyle.PRIMARY)]
        ]
    )


def request_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖ لغو", callback_data="req:cancel", style=ButtonStyle.DANGER)]
        ]
    )


async def begin_request(target: Message, state: FSMContext, query: str | None = None) -> None:
    await state.set_state(RequestStates.title)
    if query:
        await state.update_data(req_query=query[:MAX_TITLE_LEN])
        text = f"📥 درخواست «{query}» رو ثبت کنم؟\nاگه همین اسم درسته بفرستش، یا اسم کامل‌تری بنویس."
    else:
        text = ASK_REQUEST_TEXT
    await target.answer(text, reply_markup=request_cancel_keyboard())


@router.callback_query(F.data == "req:start")
async def start_request(callback: CallbackQuery, state: FSMContext) -> None:
    await begin_request(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "req:cancel")
async def cancel_request(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(CANCELLED_TEXT)
    await callback.answer(CANCELLED_TEXT)


@router.message(StateFilter(RequestStates.title), F.text & ~F.text.startswith("/"))
async def receive_request(message: Message, state: FSMContext, db: Database) -> None:
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer(TITLE_TOO_SHORT_TEXT, reply_markup=request_cancel_keyboard())
        return
    user = message.from_user
    db.add_request(
        user_id=user.id if user else 0,
        user_name=user.full_name if user else "ناشناس",
        title=title,
    )
    await state.clear()
    await message.answer(REQUEST_SAVED_TEXT)
