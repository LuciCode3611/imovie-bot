"""Subtitle card (subkade.ir post) — opened from the subtitle search results.

Rendered as a Bot API 10.1 rich message (poster + metadata table + story),
with one inline download button per subtitle file — the card itself never
changes. Falls back to a classic photo card, then to plain text, exactly like
the movie card in src/handlers/card.py.

Callback prefixes (no overlap with the movie card):
    sm:{key}        open the card
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from src.handlers.card import EXPIRED_TEXT
from src.handlers.common import edit_text_safely
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState, SubtitleCardEntry
from src.services.formatting import subtitle_card_text, subtitle_root_keyboard
from src.services.rich import rich_subtitle_message
from src.services.subkade import SubkadeClient

router = Router(name="subtitle_card")

NO_FILES_TEXT = "زیرنویس رایگانی برای این عنوان پیدا نشد."


@router.callback_query(F.data.startswith("sm:"))
async def open_subtitle_card(
    callback: CallbackQuery,
    bot: Bot,
    subkade: SubkadeClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    key = (callback.data or "").removeprefix("sm:")
    entry = card_state.get_subtitle(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    slug = entry.summary.slug
    page_key = f"sub:page:{slug}"
    details = await cache.get(page_key)
    if details is None:
        details = await subkade.subtitle(slug)
        await cache.set(page_key, details, cfg.page_ttl)
    entry.details = details
    markup = subtitle_root_keyboard(details, key, emoji_map=cfg.emoji)
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
        entry.rich = False  # older client/API — classic card below
    text = subtitle_card_text(details)
    if not details.packs:
        text += f"\n\n⚠️ {NO_FILES_TEXT}"
    poster = details.summary.poster_url
    if poster:
        try:
            await callback.message.answer_photo(poster, caption=text, reply_markup=markup)
            await callback.answer()
            return
        except TelegramBadRequest:
            pass  # poster unusable — edit the results message in place
    await edit_text_safely(callback.message, text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()
