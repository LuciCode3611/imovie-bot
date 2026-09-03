import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.models.config import Config, resolve_owner
from src.services.parsers import filter_session_cookies, parse_cookies
from src.services.zarfilm import ZarfilmClient

router = Router(name="admin")

ASK_COOKIE_TEXT = "مقدار کوکی مرورگر رو بفرست (name=value; ...)."
NO_SESSION_COOKIE_TEXT = "کوکی نشست توش نبود؛ دوباره تلاش کن."
DELETE_FAILED_TEXT = "حذف پیام کوکی ممکن نشد؛ لطفاً خودت اون پیام رو حذف کن."
SESSION_UPDATED_TEXT = "نشست به‌روزرسانی شد."


class LoginStates(StatesGroup):
    waiting_cookie = State()


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
