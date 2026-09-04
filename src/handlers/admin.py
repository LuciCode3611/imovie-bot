import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.enums.button_style import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.models.config import Config, resolve_owner
from src.services.parsers import filter_session_cookies, parse_cookies
from src.services.rich import rich_dashboard_message
from src.services.zarfilm import ZarfilmClient

router = Router(name="admin")

ASK_COOKIE_TEXT = "مقدار کوکی مرورگر رو بفرست (name=value; ...).\nبرای لغو، دکمهٔ زیر رو بزن یا /start رو بزن."
NO_SESSION_COOKIE_TEXT = "کوکی نشست توش نبود؛ دوباره تلاش کن."
DELETE_FAILED_TEXT = "حذف پیام کوکی ممکن نشد؛ لطفاً خودت اون پیام رو حذف کن."
SESSION_UPDATED_TEXT = "نشست به‌روزرسانی شد."
CANCELLED_TEXT = "لغو شد."
CHECKING_TEXT = "🔄 در حال بررسی…"
REFRESHED_TEXT = "به‌روزرسانی شد."


class LoginStates(StatesGroup):
    waiting_cookie = State()


def _owner_id(cfg: Config) -> int | None:
    return resolve_owner(cfg)


def _is_owner(user, cfg: Config) -> bool:
    return user is not None and _owner_id(cfg) is not None and user.id == _owner_id(cfg)


def cookie_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖ لغو", callback_data="dash:cancellogin", style=ButtonStyle.DANGER)]
        ]
    )


def dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بررسی اتصال", callback_data="dash:check")],
            [InlineKeyboardButton(text="🔑 ورود / تمدید کوکی", callback_data="dash:login", style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="✖ بستن", callback_data="dash:close", style=ButtonStyle.DANGER)],
        ]
    )


@router.message(F.text.startswith("/login"))
async def start_login(message: Message, state: FSMContext, cfg: Config) -> None:
    if not _is_owner(message.from_user, cfg):
        return
    await state.set_state(LoginStates.waiting_cookie)
    await message.answer(ASK_COOKIE_TEXT, reply_markup=cookie_prompt_keyboard())


# only plain (non-command) text is consumed while waiting for a cookie, so
# /start, /status etc. keep working instead of being mistaken for a cookie
@router.message(LoginStates.waiting_cookie, F.text & ~F.text.startswith("/"))
async def receive_cookie(message: Message, state: FSMContext, cfg: Config, zarfilm: ZarfilmClient) -> None:
    raw = message.text or ""
    try:
        await message.delete()
    except TelegramBadRequest:
        await message.answer(DELETE_FAILED_TEXT)
    cookies = parse_cookies(raw)
    session_cookies = filter_session_cookies(cookies)
    if not session_cookies:
        await message.answer(NO_SESSION_COOKIE_TEXT, reply_markup=cookie_prompt_keyboard())
        return  # stay in waiting state so the owner can retry
    zarfilm.set_cookies(cookies)
    zarfilm.persist_session()
    zarfilm.mark_session_ready()
    await state.clear()
    logging.info("session cookie refreshed via /login")
    await message.answer(SESSION_UPDATED_TEXT)


@router.callback_query(F.data.startswith("dash:"))
async def dashboard_action(
    callback: CallbackQuery,
    bot: Bot,
    cfg: Config,
    zarfilm: ZarfilmClient,
    state: FSMContext,
) -> None:
    if not _is_owner(callback.from_user, cfg):
        await callback.answer("فقط برای مالک.", show_alert=True)
        return
    action = (callback.data or "").removeprefix("dash:")

    if action in ("cancellogin",):
        await state.clear()
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.edit_text(CANCELLED_TEXT)
        await callback.answer(CANCELLED_TEXT)
        return

    if action == "close":
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer()
        return

    if action == "login":
        await state.set_state(LoginStates.waiting_cookie)
        await callback.message.answer(ASK_COOKIE_TEXT, reply_markup=cookie_prompt_keyboard())
        await callback.answer("کوکی رو بفرست.")
        return

    if action == "open":
        stats = await _gather_stats(zarfilm, cfg)
        await _send_dashboard(bot, callback.message, stats)
        await callback.answer()
        return

    # default: check / refresh
    await callback.answer(CHECKING_TEXT)
    stats = await _gather_stats(zarfilm, cfg)
    await _edit_dashboard(bot, callback.message, stats)
    await callback.answer(REFRESHED_TEXT)


@router.message(F.text.startswith("/status"))
async def dashboard(message: Message, bot: Bot, cfg: Config, zarfilm: ZarfilmClient) -> None:
    if not _is_owner(message.from_user, cfg):
        return
    stats = await _gather_stats(zarfilm, cfg)
    await _send_dashboard(bot, message, stats)


async def _send_dashboard(bot: Bot, target: Message, stats: dict) -> None:
    try:
        await bot.send_rich_message(
            chat_id=target.chat.id, rich_message=rich_dashboard_message(stats), reply_markup=dashboard_keyboard()
        )
    except TelegramBadRequest:
        await target.answer(_dashboard_text(stats), reply_markup=dashboard_keyboard())


async def _edit_dashboard(bot: Bot, target: Message, stats: dict) -> None:
    """Re-render the dashboard in place. The message is already a rich
    message, so edit it as rich; a TelegramBadRequest that isn't a structural
    failure is swallowed and surfaced as an alert rather than downgrading to
    the plain (messy, table-less) fallback."""
    try:
        await bot.edit_message_text(
            chat_id=target.chat.id,
            message_id=target.message_id,
            text=None,
            rich_message=rich_dashboard_message(stats),
            reply_markup=dashboard_keyboard(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in (exc.message or ""):
            return
        # last resort: edit the markup only so the user at least sees fresh
        # buttons without a broken, table-less body
        with contextlib.suppress(TelegramBadRequest):
            await target.edit_reply_markup(reply_markup=dashboard_keyboard())


async def _gather_stats(zarfilm: ZarfilmClient, cfg: Config) -> dict:
    present = zarfilm._restore_session()  # loads any persisted session
    valid: bool | None = None
    if present:
        try:
            valid = await zarfilm.session_valid()
        except Exception:  # noqa: BLE001 - the check must never break the panel
            valid = None
    return {
        "online": True,
        "session_present": present,
        "session_valid": valid,
        "ttl": zarfilm.session_ttl_seconds(),
        "uptime": zarfilm.uptime_seconds(),
        "searches": zarfilm.stats.get("searches", 0),
        "movies": zarfilm.stats.get("movies", 0),
        "open_mode": not bool(cfg.allowed_user_ids),
        "proxy": cfg.proxy_url,
    }


def _dashboard_text(stats: dict) -> str:
    if not stats.get("session_present"):
        cookie = "🔴 بدون کوکی"
    elif stats.get("session_valid") is True:
        cookie = "🟢 معتبر"
    elif stats.get("session_valid") is False:
        cookie = "🔴 منقضی شده"
    else:
        cookie = "🟡 نامشخص"
    return (
        "🛠 داشبورد مدیریت ربات\n\n"
        f"وضعیت ربات: 🟢 آنلاین\n"
        f"کوکی نشست: {cookie}\n"
        f"جستجوها: {stats.get('searches', 0)}"
    )
