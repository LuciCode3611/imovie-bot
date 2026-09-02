import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.models.config import Config
from src.services.parsers import filter_session_cookies, parse_cookie_header
from src.services.zarfilm import ZarfilmClient

router = Router(name="admin")


class LoginStates(StatesGroup):
    waiting_cookie = State()


@router.message(F.text.startswith("/login"))
async def start_login(message: Message, state: FSMContext, cfg: Config) -> None:
    user = message.from_user
    if user is None or not cfg.allowed_user_ids or user.id != cfg.allowed_user_ids[0]:
        return
    await state.set_state(LoginStates.waiting_cookie)
    await message.answer("مقدار کوکی مرورگر رو بفرست (name=value; ...).")


@router.message(LoginStates.waiting_cookie, F.text)
async def receive_cookie(message: Message, state: FSMContext, cfg: Config, zarfilm: ZarfilmClient) -> None:
    raw = message.text or ""
    await message.delete()
    cookies = parse_cookie_header(raw)
    session_cookies = filter_session_cookies(cookies)
    if not session_cookies:
        await message.answer("کوکی نشست توش نبود؛ دوباره تلاش کن.")
        return
    for name, value in cookies.items():
        zarfilm._client.cookies.set(name, value)
    cfg.session_path.write_text(json.dumps(dict(zarfilm._client.cookies)), encoding="utf-8")
    zarfilm.mark_session_ready()
    await state.clear()
    logging.info("session cookie refreshed via /login")
    await message.answer("نشست به‌روزرسانی شد.")
