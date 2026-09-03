from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.handlers.common import edit_text_safely
from src.models import MovieSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CardEntry, CallbackState
from src.services.formatting import search_keyboard, welcome_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="search")

NO_RESULTS_TEXT = "چیزی پیدا نشد؛ با املای دیگری امتحان کن."
LISTENING_TEXT = "نام فیلم یا سریال رو بنویس…"
HINT_TEXT = "برای جستجو، اول دکمهٔ جستجو رو بزن."
SEARCHING_TEXT = "🔍 در حال جستجو…"
MAX_RESULTS = 5


class SearchStates(StatesGroup):
    listening = State()


@router.callback_query(F.data == "srch:go")
async def begin_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.listening)
    if callback.message is not None:
        await edit_text_safely(callback.message, LISTENING_TEXT)
    await callback.answer()


def results_header(query: str, total: int) -> str:
    header = f"نتایج برای «{escape(query)}»"
    if total > MAX_RESULTS:
        header += f" — نمایش {MAX_RESULTS} از {total}"
    return header + ":"


@router.message(StateFilter(SearchStates.listening), F.text & ~F.text.startswith("/"))
async def handle_search(
    message: Message,
    state: FSMContext,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    query = (message.text or "").strip()
    cache_key = f"search:{query.lower()}"
    results: list[MovieSummary] | None = await cache.get(cache_key)
    if results is None:
        status = await message.answer(SEARCHING_TEXT)
        results = await zarfilm.search(query)
        await cache.set(cache_key, results, cfg.search_ttl)
    else:
        status = None
    await state.clear()
    if not results:
        if status is not None:
            await status.edit_text(NO_RESULTS_TEXT)
        else:
            await message.answer(NO_RESULTS_TEXT)
        return
    pairs: list[tuple[str, CardEntry]] = []
    for summary in results[:MAX_RESULTS]:
        entry = CardEntry(summary=summary)
        key = card_state.create(entry)
        pairs.append((key, entry))
    keyboard = search_keyboard(pairs, emoji_map=cfg.emoji)
    if status is not None:
        await status.edit_text(results_header(query, len(results)), reply_markup=keyboard)
    else:
        await message.answer(results_header(query, len(results)), reply_markup=keyboard)


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def search_hint(message: Message) -> None:
    await message.answer(HINT_TEXT, reply_markup=welcome_keyboard())
