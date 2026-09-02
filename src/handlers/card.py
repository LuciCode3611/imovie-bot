from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.formatting import (
    card_text,
    episode_list_text,
    file_keyboard,
    quality_keyboard,
    root_keyboard,
    season_quality_keyboard,
)
from src.services.zarfilm import ZarfilmClient

router = Router(name="card")

EXPIRED_TEXT = "جستجو منقضی شده؛ دوباره جستجو کن."
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
    await callback.message.edit_text(
        card_text(details),
        reply_markup=root_keyboard(details, key),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("l:"))
async def choose_language(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, audio = (callback.data or "").split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = audio
    links = getattr(entry.details, AUDIO_LINKS[audio])
    await callback.message.edit_reply_markup(reply_markup=quality_keyboard(links, key, audio))
    await callback.answer()


@router.callback_query(F.data.startswith("s:"))
async def choose_season(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, idx_text = (callback.data or "").split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = f"s:{idx_text}"
    season = entry.details.seasons[int(idx_text)]
    await callback.message.edit_reply_markup(reply_markup=season_quality_keyboard(season.qualities, key))
    await callback.answer()


@router.callback_query(F.data.startswith("q:"))
async def choose_quality(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, audio, idx_text = (callback.data or "").split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    idx = int(idx_text)
    if audio == "s":
        season_index = int(entry.selection.split(":")[1]) if entry.selection.startswith("s:") else 0
        pack = entry.details.seasons[season_index].qualities[idx]
        await callback.message.answer(episode_list_text(pack), parse_mode="HTML")
        await callback.message.edit_reply_markup(reply_markup=root_keyboard(entry.details, key))
        entry.selection = ""
        await callback.answer()
        return
    links = getattr(entry.details, AUDIO_LINKS[audio])
    await callback.message.edit_reply_markup(reply_markup=file_keyboard([links[idx]], key))
    await callback.answer()


@router.callback_query(F.data.startswith("x:"))
async def cancel(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    key = (callback.data or "").removeprefix("x:")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = ""
    await callback.message.edit_reply_markup(reply_markup=root_keyboard(entry.details, key))
    await callback.answer()
