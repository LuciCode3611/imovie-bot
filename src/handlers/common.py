import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.exceptions import AuthError, ZarfilmError
from src.models.config import Config, resolve_owner

router = Router(name="common")

START_TEXT = "نام فیلم یا سریال رو بفرست تا لینک‌های دانلودش رو پیدا کنم."
UNAVAILABLE_TEXT = "دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن."
SESSION_EXPIRED_TEXT = "نشست منقضی شده؛ با /login کوکی جدید بفرست."

_OWNER_ALERT_COOLDOWN = 600.0
_owner_alert_state = {"last": 0.0}


@router.message(F.text.startswith("/start"))
async def start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(F.text.startswith("/help"))
async def help_(message: Message) -> None:
    await message.answer(START_TEXT)


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
    if isinstance(failure, AuthError):
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
