"""Subtitle search (subkade.ir): «📝 جستجوی زیرنویس» button / ``/subtitle``.

Mirrors src/handlers/search.py one-to-one: a listening state armed by the
button or command, the animated «صبر کن پیداش کنم» status, cached results
and the same ◀ 1/3 ▶ pagination (5 per page).
"""

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from src.handlers.card import EXPIRED_TEXT
from src.handlers.common import edit_text_safely
from src.handlers.search import PAGE_SIZE, page_count, send_searching_status
from src.models import SubtitleSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.db import Database
from src.repos.state import CallbackState, SubtitleCardEntry, SubtitleSearchEntry
from src.services.formatting import subtitle_results_keyboard
from src.services.subkade import SubkadeClient

router = Router(name="subtitle_search")

LISTENING_TEXT = "نام فیلم یا سریال رو برای زیرنویس فارسی بنویس…"
NO_RESULTS_TEXT = "زیرنویسی پیدا نشد؛ با املای انگلیسی دیگری امتحان کن."


class SubtitleSearchStates(StatesGroup):
    listening = State()


@router.callback_query(F.data == "srch:sub_go")
async def begin_subtitle_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SubtitleSearchStates.listening)
    if callback.message is not None:
        await edit_text_safely(callback.message, LISTENING_TEXT)
    await callback.answer()


@router.message(F.text.startswith("/subtitle"))
async def subtitle_command(message: Message, state: FSMContext) -> None:
    """Menu shortcut for the subtitle button: arm the listening state."""
    await state.set_state(SubtitleSearchStates.listening)
    await message.answer(LISTENING_TEXT)


def results_header(query: str, total: int, page: int = 0) -> str:
    header = f"زیرنویس‌های «{escape(query)}»"
    if total > PAGE_SIZE:
        start = page * PAGE_SIZE + 1
        end = min((page + 1) * PAGE_SIZE, total)
        header += f" — نمایش {start}–{end} از {total}"
    return header + ":"


@router.message(StateFilter(SubtitleSearchStates.listening), F.text & ~F.text.startswith("/"))
async def handle_subtitle_search(
    message: Message,
    bot: Bot,
    state: FSMContext,
    subkade: SubkadeClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
    db: Database,
) -> None:
    query = (message.text or "").strip()
    cache_key = f"sub:search:{query.lower()}"
    if message.from_user is not None:
        db.increment_searches(message.from_user.id)
    results: list[SubtitleSummary] | None = await cache.get(cache_key)
    status = None
    if results is None:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            status = await send_searching_status(message)
            results = await subkade.search(query)
            await cache.set(cache_key, results, cfg.search_ttl)
    await state.clear()
    if not results:
        if status is not None:
            await status.edit_text(NO_RESULTS_TEXT)
        else:
            await message.answer(NO_RESULTS_TEXT)
        return
    pairs: list[tuple[str, SubtitleCardEntry]] = []
    for summary in results:
        entry = SubtitleCardEntry(summary=summary)
        pairs.append((card_state.create_subtitle(entry), entry))
    search_key = card_state.create_subtitle_search(SubtitleSearchEntry(query=query, pairs=pairs))
    pages = page_count(len(pairs))
    keyboard = subtitle_results_keyboard(pairs[:PAGE_SIZE], 0, pages, search_key, emoji_map=cfg.emoji)
    header = results_header(query, len(pairs))
    if status is not None:
        await status.edit_text(header, reply_markup=keyboard)
    else:
        await message.answer(header, reply_markup=keyboard)


@router.callback_query(F.data.startswith("spg:"))
async def change_subtitle_page(
    callback: CallbackQuery,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, key, value = parts
    entry = card_state.get_subtitle_search(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    if value == "i":  # page indicator, not a button
        await callback.answer()
        return
    if not value.isdigit() or int(value) >= page_count(entry.total):
        await callback.answer()
        return
    page = int(value)
    chunk = entry.pairs[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    await edit_text_safely(
        callback.message,
        results_header(entry.query, entry.total, page),
        reply_markup=subtitle_results_keyboard(chunk, page, page_count(entry.total), key, emoji_map=cfg.emoji),
    )
    await callback.answer()
