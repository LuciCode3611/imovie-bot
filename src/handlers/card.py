from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.formatting import card_text, root_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="card")

EXPIRED_TEXT = "جستجو منقضی شده؛ دوباره جستجو کن."


@router.callback_query(F.data.startswith("m:"))
async def open_card(
    callback: CallbackQuery,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    key = (callback.data or "").removeprefix("m:")
    entry = card_state.get(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    slug = entry.summary.slug
    page_key = f"page:{slug}"
    details = await cache.get(page_key)
    if details is None:
        details = await zarfilm.movie(slug)
        await cache.set(page_key, details, cfg.page_ttl)
    entry.details = details
    await callback.message.edit_text(
        card_text(details),
        reply_markup=root_keyboard(details, key),
        parse_mode="HTML",
    )
    await callback.answer()
