"""Subtitle card (subkade.ir post) — opened from the subtitle search results.

Rendered as a Bot API 10.1 rich message (poster + metadata table + story +
table of every free Persian pack). Falls back to a classic photo card, then
to plain text, exactly like the movie card in src/handlers/card.py.

Callback prefixes (no overlap with the movie card):
    sm:{key}        open the card
    sp:{key}:{idx}  open one pack (season) → file buttons
    sx:{key}        back to the card root
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage, Message

from src.handlers.card import EXPIRED_TEXT, INVALID_PATH_TEXT
from src.handlers.common import edit_card_content, edit_rich_content, edit_text_safely
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState, SubtitleCardEntry
from src.services.formatting import (
    subtitle_card_text,
    subtitle_pack_caption,
    subtitle_pack_keyboard,
    subtitle_root_keyboard,
)
from src.services.rich import rich_subtitle_message, rich_subtitle_pack_message
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
    entry.pack = None
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


async def _render(
    *,
    bot: Bot,
    message: Message,
    entry: SubtitleCardEntry,
    rich_message: InputRichMessage,
    classic_text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if entry.rich:
        await edit_rich_content(bot, message, rich_message, reply_markup)
    else:
        await edit_card_content(message, classic_text, reply_markup)


@router.callback_query(F.data.startswith("sp:"))
async def open_subtitle_pack(callback: CallbackQuery, bot: Bot, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, idx_text = parts
    entry = card_state.get_subtitle(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    idx = int(idx_text)
    if idx >= len(entry.details.packs):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    pack = entry.details.packs[idx]
    if not pack.files:
        await callback.answer(NO_FILES_TEXT, show_alert=True)
        return
    entry.pack = idx
    await _render(
        bot=bot,
        message=callback.message,
        entry=entry,
        rich_message=rich_subtitle_pack_message(entry.details, pack),
        classic_text=subtitle_pack_caption(entry.details, pack),
        reply_markup=subtitle_pack_keyboard(pack, key),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sx:"))
async def back_to_subtitle_root(callback: CallbackQuery, bot: Bot, card_state: CallbackState, cfg: Config, **_: object) -> None:
    key = (callback.data or "").removeprefix("sx:")
    entry = card_state.get_subtitle(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.pack = None
    await _render(
        bot=bot,
        message=callback.message,
        entry=entry,
        rich_message=rich_subtitle_message(entry.details),
        classic_text=subtitle_card_text(entry.details),
        reply_markup=subtitle_root_keyboard(entry.details, key, emoji_map=cfg.emoji),
    )
    await callback.answer()
