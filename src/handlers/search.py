from aiogram import F, Router
from aiogram.types import Message

from src.models import MovieSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CardEntry, CallbackState
from src.services.formatting import search_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="search")

NO_RESULTS_TEXT = "چیزی پیدا نشد؛ با املای دیگری امتحان کن."
MAX_RESULTS = 5


@router.message(F.text & ~F.text.startswith("/"))
async def handle_search(
    message: Message,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    query = (message.text or "").strip()
    cache_key = f"search:{query.lower()}"
    results: list[MovieSummary] | None = await cache.get(cache_key)
    if results is None:
        results = await zarfilm.search(query)
        await cache.set(cache_key, results, cfg.search_ttl)
    if not results:
        await message.answer(NO_RESULTS_TEXT)
        return
    pairs: list[tuple[str, CardEntry]] = []
    for summary in results[:MAX_RESULTS]:
        entry = CardEntry(summary=summary)
        key = card_state.create(entry)
        pairs.append((key, entry))
    await message.answer("نتایج جستجو:", reply_markup=search_keyboard(pairs))
