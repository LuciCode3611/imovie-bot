import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.exceptions import ZarfilmError

router = Router(name="common")

START_TEXT = "نام فیلم یا سریال رو بفرست تا لینک‌های دانلودش رو پیدا کنم."
UNAVAILABLE_TEXT = "دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن."


@router.message(F.text.startswith("/start"))
async def start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(F.text.startswith("/help"))
async def help_(message: Message) -> None:
    await message.answer(START_TEXT)


@router.errors()
async def on_error(event: TelegramObject, exception: Exception | None = None) -> bool:
    failure = exception or getattr(event, "exception", None)
    if isinstance(failure, ZarfilmError):
        logging.warning("source failure: %s", failure)
    else:
        logging.exception("unhandled bot error: %s", failure)
    update = getattr(event, "update", event)
    target = update.message or update.callback_query
    if isinstance(target, Message):
        await target.answer(UNAVAILABLE_TEXT)
    elif isinstance(target, CallbackQuery):
        await target.answer(UNAVAILABLE_TEXT, show_alert=True)
    return True
