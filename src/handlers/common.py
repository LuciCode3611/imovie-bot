import html
import logging
import re
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

# animated custom emoji used across the welcome message; the bot needs a
# Premium-associated account to send them — otherwise we strip the tags and use
# the unicode fallback.
GREETING_EMOJI_ID = "5440660757194744323"
GREETING_EMOJI_FALLBACK = "👋"
DOWNLOAD_EMOJI_ID = "5325547803936572038"
DOWNLOAD_EMOJI_FALLBACK = "📥"
GUIDE_EMOJI_ID = "5467538555158943525"
GUIDE_EMOJI_FALLBACK = "📖"

_TG_EMOJI_TAG = re.compile(r'<tg-emoji emoji-id="\d+">([^<]*)</tg-emoji>')


def welcome_text(full_name: str | None) -> str:
    """Personalised welcome (HTML parse mode): greeting with the user's name,
    a one-line description and a blockquote quick guide."""
    name = html.escape(full_name) if full_name else "دوست"
    greeting = f'<tg-emoji emoji-id="{GREETING_EMOJI_ID}">{GREETING_EMOJI_FALLBACK}</tg-emoji>'
    download = f'<tg-emoji emoji-id="{DOWNLOAD_EMOJI_ID}">{DOWNLOAD_EMOJI_FALLBACK}</tg-emoji>'
    guide = f'<tg-emoji emoji-id="{GUIDE_EMOJI_ID}">{GUIDE_EMOJI_FALLBACK}</tg-emoji>'
    return (
        f"سلام {name} عزیز {greeting}\n\n"
        f"با این ربات میتونی هر فیلم و سریال یا انیمه ای که دوست داری دانلود کنی {download}\n\n"
        f"<blockquote><b>راهنمای سریع {guide}</b>\n"
        "۱. دکمهٔ 🔍 جستجو رو بزن.\n"
        "۲. نام فیلم یا سریال رو به انگلیسی بنویس.\n"
        "۳. با دکمه‌های کنار پیام، زبان و کیفیت (یا فصل) رو انتخاب کن تا به لینک دانلود برسی.\n"
        "۴. زیرنویس فارسی می‌خوای؟ دکمهٔ 📝 جستجوی زیرنویس (یا /subtitle) رو بزن."
        "</blockquote>"
    )


async def send_welcome(message: Message, cfg: Config | None) -> None:
    full_name = message.from_user.full_name if message.from_user is not None else None
    is_owner = _is_owner_message(message, cfg)
    text = welcome_text(full_name)
    try:
        await message.answer(text, parse_mode="HTML", reply_markup=welcome_keyboard(is_owner=is_owner))
    except TelegramBadRequest:
        # custom emoji / blockquote unsupported — resend with plain unicode
        await message.answer(
            _TG_EMOJI_TAG.sub(r"\1", text),
            reply_markup=welcome_keyboard(is_owner=is_owner),
        )


UNAVAILABLE_TEXT = "دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن."
NOT_FOUND_TEXT = "این عنوان دیگه موجود نیست یا حذف شده."
SESSION_EXPIRED_TEXT = "نشست منقضی شده؛ با /login کوکی جدید بفرست."
# what a non-owner sees when the bot's site session has expired
SERVICE_DOWN_TEXT = "😅 ربات فعلاً در دسترس نیست؛ به‌زودی برمی‌گردیم. کمی بعد دوباره تلاش کن."

NOT_MODIFIED_MARKER = "message is not modified"

_OWNER_ALERT_COOLDOWN = 600.0
_owner_alert_state = {"last": float("-inf")}


def _is_owner_message(message: Message, cfg: Config | None) -> bool:
    if cfg is None or message.from_user is None:
        return False
    owner = resolve_owner(cfg)
    return owner is not None and message.from_user.id == owner


@router.message(F.text.startswith("/start"))
async def start(message: Message, state: FSMContext, cfg: Config) -> None:
    await state.clear()
    await send_welcome(message, cfg)


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


async def edit_card_content(message: Message, text: str, reply_markup: Any) -> None:
    """Update a card in place: photo messages edit their caption, text
    messages edit their body. Keeps the card as a single edited message so
    drilling in and back never spawns extra messages."""
    if message.content_type != "text":
        try:
            await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
            return
        except TelegramBadRequest as exc:
            if NOT_MODIFIED_MARKER in (exc.message or ""):
                return
    await edit_text_safely(message, text, reply_markup=reply_markup, parse_mode="HTML")


async def edit_rich_content(bot: Bot, message: Message, rich_message: Any, reply_markup: Any) -> None:
    """Edit a Bot API 10.1 rich message in place (body via rich_message)."""
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=None,
            rich_message=rich_message,
            reply_markup=reply_markup,
        )
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
            text = SERVICE_DOWN_TEXT
            await _alert_owner(bot, owner_id)
    if isinstance(target, Message):
        await target.answer(text)
    elif isinstance(target, CallbackQuery):
        await target.answer(text, show_alert=True)
    return True
