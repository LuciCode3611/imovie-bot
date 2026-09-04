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

from src.handlers.common import edit_text_safely
from src.models.config import Config, resolve_owner
from src.services.parsers import filter_session_cookies, parse_cookies
from src.services.rich import rich_dashboard_message
from src.services.zarfilm import ZarfilmClient

router = Router(name="admin")

ASK_COOKIE_TEXT = "مقدار کوکی مرورگر رو بفرست (name=value; ...)."
NO_SESSION_COOKIE_TEXT = "کوکی نشست توش نبود؛ دوباره تلاش کن."
DELETE_FAILED_TEXT = "حذف پیام کوکی ممکن نشد؛ لطفاً خودت اون پیام رو حذف کن."
SESSION_UPDATED_TEXT = "نشست به‌روزرسانی شد."
REFRESHED_TEXT = "به‌روزرسانی شد."
COOKIE_EXPIRED_OWNER_TEXT = "کوکی نشست منقضی شده؛ با /login کوکی تازه بفرست."

CHECKING_TEXT = "🔄 در حال بررسی…"


class LoginStates(StatesGroup):
    waiting_cookie = State()


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
    user = message.from_user
    if user is None or user.id != resolve_owner(cfg):
        return
    await state.set_state(LoginStates.waiting_cookie)
    await message.answer(ASK_COOKIE_TEXT)


@router.message(LoginStates.waiting_cookie, F.text)
async def receive_cookie(message: Message, state: FSMContext, cfg: Config, zarfilm: ZarfilmClient) -> None:
    raw = message.text or ""
    try:
        await message.delete()
    except TelegramBadRequest:
        await message.answer(DELETE_FAILED_TEXT)
    cookies = parse_cookies(raw)
    session_cookies = filter_session_cookies(cookies)
    if not session_cookies:
        await message.answer(NO_SESSION_COOKIE_TEXT)
        return
    zarfilm.set_cookies(cookies)
    zarfilm.persist_session()
    zarfilm.mark_session_ready()
    await state.clear()
    logging.info("session cookie refreshed via /login")
    await message.answer(SESSION_UPDATED_TEXT)


@router.message(F.text.startswith("/status"))
async def dashboard(message: Message, bot: Bot, cfg: Config, zarfilm: ZarfilmClient) -> None:
    user = message.from_user
    if user is None or user.id != resolve_owner(cfg):
        return
    stats = await _gather_stats(zarfilm)
    try:
        await bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=rich_dashboard_message(stats),
            reply_markup=dashboard_keyboard(),
        )
    except TelegramBadRequest:
        await message.answer(_dashboard_text(stats), reply_markup=dashboard_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.startswith("dash:"))
async def dashboard_action(
    callback: CallbackQuery,
    bot: Bot,
    cfg: Config,
    zarfilm: ZarfilmClient,
    state: FSMContext,
) -> None:
    user = callback.from_user
    if user is None or user.id != resolve_owner(cfg):
        await callback.answer("فقط برای مالک.", show_alert=True)
        return
    action = (callback.data or "").removeprefix("dash:")
    if action == "close":
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer()
        return
    if action == "login":
        await state.set_state(LoginStates.waiting_cookie)
        await callback.answer(ASK_COOKIE_TEXT, show_alert=True)
        await callback.message.answer(ASK_COOKIE_TEXT)
        return
    # default: check / refresh
    await callback.answer(CHECKING_TEXT)
    stats = await _gather_stats(zarfilm)
    keyboard = dashboard_keyboard()
    try:
        await bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=None,
            rich_message=rich_dashboard_message(stats),
            reply_markup=keyboard,
        )
    except TelegramBadRequest:
        await edit_text_safely(callback.message, _dashboard_text(stats), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer(REFRESHED_TEXT)


async def _gather_stats(zarfilm: ZarfilmClient) -> dict:
    present = zarfilm._restore_session()
    stats = {
        "online": True,
        "session_present": present,
        "session_valid": None,
        "ttl": zarfilm.session_ttl_seconds(),
    }
    if present:
        try:
            stats["session_valid"] = await zarfilm.session_valid()
        except Exception:  # noqa: BLE001 - a check failure must not break the dashboard
            stats["session_valid"] = None
    return stats


def _dashboard_text(stats: dict) -> str:
    if not stats.get("session_present"):
        cookie = "🔴 بدون کوکی"
    elif stats.get("session_valid") is True:
        cookie = "🟢 معتبر"
    elif stats.get("session_valid") is False:
        cookie = "🔴 منقضی شده"
    else:
        cookie = "🟡 نامشخص"
    online = "🟢 آنلاین" if stats.get("online") else "🔴 آفلاین"
    ttl = stats.get("ttl")
    ttl_text = "—"
    if ttl is not None:
        days, rem = divmod(int(ttl), 86400)
        ttl_text = f"{days} روز" if days else f"{rem // 3600} ساعت"
    return f"🛠 داشبورد مدیریت ربات\n\nوضعیت ربات: {online}\nکوکی نشست: {cookie}\nاعتبار باقی‌مانده: {ttl_text}"
