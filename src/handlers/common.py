import logging
import time
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.exceptions import AuthError, NotFoundError, ZarfilmError
from src.models.config import Config, resolve_owner
from src.services.formatting import welcome_keyboard

router = Router(name="common")

WELCOME_TEXT = (
    "سلام! با این ربات می‌تونی فیلم و سریال جستجو کنی و لینک‌های دانلود مستقیم بگیری.\n\n"
    "راهنمای سریع:\n"
    "۱. دکمهٔ 🔍 جستجو رو بزن.\n"
    "۲. نام فیلم یا سریال رو به فارسی یا انگلیسی بنویس.\n"
    "۳. با دکمه‌های کنار پیام، زبان و کیفیت (یا فصل) رو انتخاب کن تا به لینک دانلود برسی."
)
UNAVAILABLE_TEXT = "دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن."
NOT_FOUND_TEXT = "این عنوان دیگه موجود نیست یا حذف شده."
SESSION_EXPIRED_TEXT = "نشست منقضی شده؛ با /login کوکی جدید بفرست."

NOT_MODIFIED_MARKER = "message is not modified"

_OWNER_ALERT_COOLDOWN = 600.0
_owner_alert_state = {"last": 0.0}


@router.message(F.text.startswith("/start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=welcome_keyboard())


@router.message(F.text.startswith("/help"))
async def help_(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=welcome_keyboard())


async def edit_text_safely(message: Message, text: str, **kwargs: Any) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        if NOT_MODIFIED_MARKER not in (exc.message or ""):
            raise


async def edit_markup_safely(message: Message, reply_markup: Any) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if NOT_MODIFIED_MARKER not in (exc.message or ""):
            raise


def _requester_id(target: Message | CallbackQuery | None) -> int | None:
    user = getattr(target, "from_user", None)
    return user.id if user is not None and isinstance(user.id, int) else None


async def _alert_owner(bot: Bot | None, owner_id: int | None) -> None:
    if bot is None or owner_id is None:
        return
    now = time.monotonic()
    if now - _owner_alert_state["last"] < _OWNER_ALERT_COOLDOWN:
        return
    _owner_alert_state["last"] = now
    try:
        await bot.send_message(owner_id, SESSION_EXPIRED_TEXT)
    except Exception:  # noqa: BLE001 - alerting must never break the error observer
        logging.warning("owner session-expiry alert could not be delivered")


@router.errors()
async def on_error(
    event: TelegramObject,
    exception: Exception | None = None,
    bot: Bot | None = None,
    cfg: Config | None = None,
) -> bool:
    failure = exception or getattr(event, "exception", None)
    if isinstance(failure, ZarfilmError):
        logging.warning("source failure: %s", failure)
    else:
        logging.exception("unhandled bot error: %s", failure)
    update = getattr(event, "update", event)
    target = update.message or update.callback_query
    text = UNAVAILABLE_TEXT
    if isinstance(failure, NotFoundError):
        text = NOT_FOUND_TEXT
    elif isinstance(failure, AuthError):  # covers SessionExpiredError
        requester_id = _requester_id(target)
        owner_id = resolve_owner(cfg) if cfg is not None else None
        if requester_id is not None and requester_id == owner_id:
            text = SESSION_EXPIRED_TEXT
        else:
            await _alert_owner(bot, owner_id)
    if isinstance(target, Message):
        await target.answer(text)
    elif isinstance(target, CallbackQuery):
        await target.answer(text, show_alert=True)
    return True
