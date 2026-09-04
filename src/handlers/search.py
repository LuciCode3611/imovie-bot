from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from src.handlers.card import EXPIRED_TEXT
from src.handlers.common import edit_text_safely
from src.models import MovieSummary
from src.models.config import Config, resolve_owner
from src.repos.cache import TTLCache
from src.repos.db import Database
from src.repos.state import CallbackState, CardEntry, SearchEntry
from src.services.formatting import results_keyboard, welcome_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="search")

NO_RESULTS_TEXT = "چیزی پیدا نشد؛ با املای دیگری امتحان کن."
LISTENING_TEXT = "نام فیلم یا سریال رو بنویس…"
HINT_TEXT = "برای جستجو، اول دکمهٔ جستجو رو بزن."
SEARCHING_TEXT = "صبر کن پیداش کنم"
# animated loading custom emoji appended to the searching status
SEARCHING_EMOJI_ID = "5429411030960711866"
SEARCHING_EMOJI_FALLBACK = "🔍"
PAGE_SIZE = 5


def searching_status() -> str:
    """HTML status with an animated custom emoji at the end; bots fall back to
    the alternative unicode emoji when custom emoji can't be sent."""
    return (
        f'{SEARCHING_TEXT} '
        f'<tg-emoji emoji-id="{SEARCHING_EMOJI_ID}">{SEARCHING_EMOJI_FALLBACK}</tg-emoji>'
    )


async def send_searching_status(message: Message) -> Message:
    """Post the searching status, retrying without the custom emoji if Telegram
    rejects it (e.g. the owner has no Telegram Premium)."""
    try:
        return await message.answer(searching_status(), parse_mode="HTML")
    except TelegramBadRequest:
        return await message.answer(f"{SEARCHING_TEXT} {SEARCHING_EMOJI_FALLBACK}")


class SearchStates(StatesGroup):
    listening = State()


@router.callback_query(F.data == "srch:go")
async def begin_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.listening)
    if callback.message is not None:
        await edit_text_safely(callback.message, LISTENING_TEXT)
    await callback.answer()


def page_count(total: int) -> int:
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def results_header(query: str, total: int, page: int = 0) -> str:
    header = f"نتایج برای «{escape(query)}»"
    if total > PAGE_SIZE:
        start = page * PAGE_SIZE + 1
        end = min((page + 1) * PAGE_SIZE, total)
        header += f" — نمایش {start}–{end} از {total}"
    return header + ":"


@router.message(StateFilter(SearchStates.listening), F.text & ~F.text.startswith("/"))
async def handle_search(
    message: Message,
    bot: Bot,
    state: FSMContext,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
    db: Database,
) -> None:
    query = (message.text or "").strip()
    cache_key = f"search:{query.lower()}"
    if message.from_user is not None:
        db.increment_searches(message.from_user.id)
    results: list[MovieSummary] | None = await cache.get(cache_key)
    status = None
    if results is None:
        # live "typing…" indicator for the whole fetch, plus a status message
        # with the animated custom emoji
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            status = await send_searching_status(message)
            results = await zarfilm.search(query)
            await cache.set(cache_key, results, cfg.search_ttl)
    await state.clear()
    if not results:
        # remember the failed query for the one-tap «ثبت درخواست» button
        await state.update_data(req_query=query[:200])
        from src.handlers.requests import request_prompt_keyboard

        text = f"{NO_RESULTS_TEXT}\n\nمی‌تونی این عنوان رو به ما درخواست بدی 👇"
        if status is not None:
            await status.edit_text(text, reply_markup=request_prompt_keyboard())
        else:
            await message.answer(text, reply_markup=request_prompt_keyboard())
        return
    pairs: list[tuple[str, CardEntry]] = []
    for summary in results:
        entry = CardEntry(summary=summary)
        pairs.append((card_state.create(entry), entry))
    search_key = card_state.create_search(SearchEntry(query=query, pairs=pairs))
    pages = page_count(len(pairs))
    keyboard = results_keyboard(pairs[:PAGE_SIZE], 0, pages, search_key, emoji_map=cfg.emoji)
    header = results_header(query, len(pairs))
    if status is not None:
        await status.edit_text(header, reply_markup=keyboard)
    else:
        await message.answer(header, reply_markup=keyboard)


@router.callback_query(F.data.startswith("pg:"))
async def change_page(
    callback: CallbackQuery,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, key, value = parts
    entry = card_state.get_search(key)
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
        reply_markup=results_keyboard(chunk, page, page_count(entry.total), key, emoji_map=cfg.emoji),
    )
    await callback.answer()


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def search_hint(message: Message, cfg: Config) -> None:
    is_owner = message.from_user is not None and message.from_user.id == resolve_owner(cfg)
    await message.answer(HINT_TEXT, reply_markup=welcome_keyboard(is_owner=is_owner))
