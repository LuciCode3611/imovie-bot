from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from src.handlers.common import edit_card_content, edit_markup_safely, edit_text_safely
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.formatting import (
    card_text,
    episode_caption,
    episode_keyboard,
    episode_page_count,
    file_keyboard,
    quality_keyboard,
    root_keyboard,
    season_quality_keyboard,
)
from src.services.zarfilm import ZarfilmClient

router = Router(name="card")

EXPIRED_TEXT = "جستجو منقضی شده؛ دوباره جستجو کن."
NO_LINKS_TEXT = "لینک دانلودی برای این عنوان پیدا نشد."
INVALID_PATH_TEXT = "انتخاب نامعتبره؛ از کارت شروع کن."
AUDIO_LINKS: dict[str, str] = {"orig": "originals", "dub": "dubs"}


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
    has_links = bool(details.originals or details.dubs or details.seasons)
    text = card_text(details) if has_links else f"{card_text(details)}\n\n⚠️ {NO_LINKS_TEXT}"
    poster = details.summary.poster_url
    if poster:
        markup = root_keyboard(details, key, emoji_map=cfg.emoji) if has_links else None
        try:
            # a new poster message keeps the search list available for other results
            await callback.message.answer_photo(poster, caption=text, reply_markup=markup)
            await callback.answer()
            return
        except TelegramBadRequest:
            pass  # poster URL unusable — fall back to editing in place
    await edit_text_safely(
        callback.message,
        text,
        reply_markup=root_keyboard(details, key, emoji_map=cfg.emoji) if has_links else None,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("l:"))
async def choose_language(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[2] not in AUDIO_LINKS:
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, audio = parts
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = audio
    links = getattr(entry.details, AUDIO_LINKS[audio])
    await edit_markup_safely(
        callback.message,
        reply_markup=quality_keyboard(links, key, audio, emoji_map=cfg.emoji),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("s:"))
async def choose_season(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, idx_text = parts
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    idx = int(idx_text)
    if idx >= len(entry.details.seasons):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    entry.selection = f"s:{idx_text}"
    entry.pack = None
    season = entry.details.seasons[idx]
    await edit_markup_safely(
        callback.message,
        reply_markup=season_quality_keyboard(season.qualities, key, season_index=idx, emoji_map=cfg.emoji),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bs:"))
async def back_to_season(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, idx_text = parts
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    idx = int(idx_text)
    if idx >= len(entry.details.seasons):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    entry.selection = f"s:{idx_text}"
    entry.pack = None
    season = entry.details.seasons[idx]
    # restore the card caption (episode view replaced it) and show qualities
    await edit_card_content(
        callback.message,
        card_text(entry.details),
        season_quality_keyboard(season.qualities, key, season_index=idx, emoji_map=cfg.emoji),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("q:"))
async def choose_quality(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, audio, idx_text = parts
    idx = int(idx_text)
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    if audio == "s":
        season_index = _selected_season(entry.selection)
        if season_index is None or season_index >= len(entry.details.seasons):
            await callback.answer(INVALID_PATH_TEXT, show_alert=True)
            return
        season = entry.details.seasons[season_index]
        if idx >= len(season.qualities):
            await callback.answer(INVALID_PATH_TEXT, show_alert=True)
            return
        pack = season.qualities[idx]
        if not pack.episodes:
            await callback.answer(NO_LINKS_TEXT, show_alert=True)
            return
        # episode list lives on the same card message — paginated, never a
        # separate message
        entry.selection = f"s:{season_index}"
        entry.pack = idx
        await edit_card_content(
            callback.message,
            episode_caption(pack, season, page=0),
            episode_keyboard(pack, key, season_index, page=0),
        )
        await callback.answer()
        return
    if audio not in AUDIO_LINKS:
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    links = getattr(entry.details, AUDIO_LINKS[audio])
    if idx >= len(links):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    await edit_markup_safely(
        callback.message,
        reply_markup=file_keyboard([links[idx]], key, emoji_map=cfg.emoji),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("e:"))
async def flip_episode_page(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdigit() or not (parts[3].isdigit() or parts[3] == "i"):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    _, key, season_text, page_text = parts
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    season_index = int(season_text)
    if season_index >= len(entry.details.seasons):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    season = entry.details.seasons[season_index]
    # the open pack is the quality chosen when the episode view was opened
    pack_index = entry.pack
    if pack_index is None or pack_index >= len(season.qualities):
        await callback.answer(INVALID_PATH_TEXT, show_alert=True)
        return
    pack = season.qualities[pack_index]
    if page_text == "i":  # page indicator, not a button
        await callback.answer()
        return
    page = int(page_text)
    if page >= episode_page_count(pack):
        await callback.answer()
        return
    entry.selection = f"s:{season_text}"
    entry.pack = pack_index
    await edit_card_content(
        callback.message,
        episode_caption(pack, season, page=page),
        episode_keyboard(pack, key, season_index, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("x:"))
async def cancel(callback: CallbackQuery, card_state: CallbackState, cfg: Config, **_: object) -> None:
    key = (callback.data or "").removeprefix("x:")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = ""
    entry.pack = None
    await edit_card_content(
        callback.message,
        card_text(entry.details),
        root_keyboard(entry.details, key, emoji_map=cfg.emoji),
    )
    await callback.answer()


def _selected_season(selection: str) -> int | None:
    if not selection.startswith("s:"):
        return None
    value = selection.split(":", 1)[1]
    return int(value) if value.isdigit() else None
