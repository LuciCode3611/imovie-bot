"""Subtitle card (SubDL title) — opened from the subtitle search results.

Rendered as a Bot API 10.1 rich message (centered metadata table), with one
inline download button per Persian subtitle file — a public ``dl.subdl.com``
zip link, never an authenticated one. Clients that predate rich messages get
the plain text card instead, like src/handlers/card.py does for movies.

Callback prefixes (no overlap with the movie card):
    sm:{key}        open the card
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from src.handlers.card import EXPIRED_TEXT
from src.handlers.subtitle_search import DISABLED_TEXT
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.formatting import subtitle_card_text, subtitle_root_keyboard
from src.services.rich import rich_subtitle_message
from src.services.subdl import SubdlClient

router = Router(name="subtitle_card")

NO_FILES_TEXT = "زیرنویس فارسی برای این عنوان پیدا نشد."


@router.callback_query(F.data.startswith("sm:"))
async def open_subtitle_card(
    callback: CallbackQuery,
    bot: Bot,
    subdl: SubdlClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    key = (callback.data or "").removeprefix("sm:")
    entry = card_state.get_subtitle(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    if not subdl.enabled:
        await callback.answer(DISABLED_TEXT, show_alert=True)
        return
    title_key = f"sub:details:{entry.summary.key}"
    details = await cache.get(title_key)
    if details is None:
        details = await subdl.details(entry.summary)
        await cache.set(title_key, details, cfg.page_ttl)
    entry.details = details
    markup = subtitle_root_keyboard(details, emoji_map=cfg.emoji)
    if details.packs:
        try:
            await bot.send_rich_message(
                chat_id=callback.message.chat.id,
                rich_message=rich_subtitle_message(details),
                reply_markup=markup,
            )
            entry.rich = True
            await callback.answer()
            return
        except TelegramBadRequest:
            pass  # older client/API — classic card below
    entry.rich = False
    text = subtitle_card_text(details)
    if not details.packs:
        text += f"\n\n⚠️ {NO_FILES_TEXT}"
    # a NEW message, never an edit: SubDL has no posters to send as a photo and
    # overwriting the results list would throw away the other titles
    await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()
