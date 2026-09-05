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

from src.handlers import admin_views
from src.models.config import Config, resolve_owner
from src.repos.db import Database
from src.services.parsers import filter_session_cookies, parse_cookies
from src.services.subkade import SubkadeClient
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
    return admin_views.overview_keyboard()


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
    db: Database,
    subkade: SubkadeClient | None = None,
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
        stats = await _gather_stats(zarfilm, cfg, db, subkade)
        await _send_view(
            bot,
            callback.message,
            rich=admin_views.overview_rich(stats),
            text=admin_views.overview_text(stats),
            markup=admin_views.overview_keyboard(),
        )
        await callback.answer()
        return

    # default: check / refresh
    await callback.answer(CHECKING_TEXT)
    stats = await _gather_stats(zarfilm, cfg, db, subkade)
    await _edit_overview(bot, callback.message, stats)
    await callback.answer(REFRESHED_TEXT)


@router.message(F.text.startswith("/status"))
async def dashboard(message: Message, bot: Bot, cfg: Config, zarfilm: ZarfilmClient, db: Database, subkade: SubkadeClient | None = None) -> None:
    if not _is_owner(message.from_user, cfg):
        return
    stats = await _gather_stats(zarfilm, cfg, db, subkade)
    await _send_overview(bot, message, stats)


async def _send_overview(bot: Bot, target: Message, stats: dict) -> None:
    try:
        await bot.send_rich_message(
            chat_id=target.chat.id,
            rich_message=admin_views.overview_rich(stats),
            reply_markup=admin_views.overview_keyboard(),
        )
    except TelegramBadRequest:
        await target.answer(
            admin_views.overview_text(stats),
            reply_markup=admin_views.overview_keyboard(),
            parse_mode="HTML",
        )


async def _edit_overview(bot: Bot, target: Message, stats: dict) -> None:
    """Re-render the overview in place; on a structural failure edit markup
    only so the user still sees fresh buttons rather than a downgraded body."""
    try:
        await bot.edit_message_text(
            chat_id=target.chat.id,
            message_id=target.message_id,
            text=None,
            rich_message=admin_views.overview_rich(stats),
            reply_markup=admin_views.overview_keyboard(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in (exc.message or ""):
            return
        with contextlib.suppress(TelegramBadRequest):
            await target.edit_reply_markup(reply_markup=admin_views.overview_keyboard())


async def _send_view(
    bot: Bot,
    target: Message,
    *,
    rich: object,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Edit the dashboard message into a management view (users/requests);
    fall back to a plain edit when the rich edit fails."""
    try:
        await bot.edit_message_text(
            chat_id=target.chat.id,
            message_id=target.message_id,
            text=None,
            rich_message=rich,
            reply_markup=markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in (exc.message or ""):
            return
        with contextlib.suppress(TelegramBadRequest):
            await target.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:"))
async def admin_manage(
    callback: CallbackQuery,
    bot: Bot,
    cfg: Config,
    db: Database,
) -> None:
    if not _is_owner(callback.from_user, cfg):
        await callback.answer("فقط برای مالک.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) > 1 else "nop"

    if action in ("nop", "noop"):
        await callback.answer()
        return

    if action == "users":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        total = db.count_users()
        users = db.list_users(limit=admin_views.USERS_PAGE, offset=page * admin_views.USERS_PAGE)
        await _send_view(
            bot,
            callback.message,
            rich=admin_views.users_rich(users, page, total),
            text=admin_views.users_text(users, page, total),
            markup=admin_views.users_keyboard(users, page, total),
        )
        await callback.answer()
        return

    if action == "reqs":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        total = db.count_open_requests()
        reqs = db.list_requests("open", limit=admin_views.REQUESTS_PAGE, offset=page * admin_views.REQUESTS_PAGE)
        await _send_view(
            bot,
            callback.message,
            rich=admin_views.requests_rich(reqs, page, total),
            text=admin_views.requests_text(reqs, page, total),
            markup=admin_views.requests_keyboard(reqs, page, total),
        )
        await callback.answer()
        return

    if action in ("blk", "unblk"):
        user_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        if user_id and user_id != _owner_id(cfg):
            db.set_blocked(user_id, action == "blk")
        total = db.count_users()
        users = db.list_users(limit=admin_views.USERS_PAGE)
        await _send_view(
            bot,
            callback.message,
            rich=admin_views.users_rich(users, 0, total),
            text=admin_views.users_text(users, 0, total),
            markup=admin_views.users_keyboard(users, 0, total),
        )
        await callback.answer("انجام شد.")
        return

    if action in ("rdone", "rrej"):
        req_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        if req_id:
            db.set_request_status(req_id, "done" if action == "rdone" else "rejected")
        total = db.count_open_requests()
        reqs = db.list_requests("open", limit=admin_views.REQUESTS_PAGE)
        await _send_view(
            bot,
            callback.message,
            rich=admin_views.requests_rich(reqs, 0, total),
            text=admin_views.requests_text(reqs, 0, total),
            markup=admin_views.requests_keyboard(reqs, 0, total),
        )
        await callback.answer("درخواست به‌روزرسانی شد.")
        return

    await callback.answer()


async def _gather_stats(zarfilm: ZarfilmClient, cfg: Config, db: Database | None = None, subkade: SubkadeClient | None = None) -> dict:
    present = zarfilm._restore_session()  # loads any persisted session
    valid: bool | None = None
    if present:
        try:
            valid = await zarfilm.session_valid()
        except Exception:  # noqa: BLE001 - the check must never break the panel
            valid = None
    stats = {
        "online": True,
        "session_present": present,
        "session_valid": valid,
        "ttl": zarfilm.session_ttl_seconds(),
        "uptime": zarfilm.uptime_seconds(),
        "ttl_human": admin_views.persian_ttl(zarfilm.session_ttl_seconds()),
        "uptime_human": admin_views.persian_ttl(zarfilm.uptime_seconds()),
        "searches": zarfilm.stats.get("searches", 0),
        "movies": zarfilm.stats.get("movies", 0),
        "open_mode": not bool(cfg.allowed_user_ids),
        "proxy": cfg.proxy_url,
        # subkade counters are in-process only (no persisted aggregate yet)
        "sub_searches": subkade.stats.get("searches", 0) if subkade is not None else 0,
        "sub_pages": subkade.stats.get("pages", 0) if subkade is not None else 0,
    }
    if db is not None:
        stats.update(db.stats())
        # keep the in-process search counter distinct from the persisted one
        stats["searches_total"] = db.total_searches()
    return stats
