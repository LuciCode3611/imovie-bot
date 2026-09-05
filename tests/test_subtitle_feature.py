"""Subtitle system: models/state, keyboards, rich builders and the handlers
(search → pagination → card → pack → back), plus the /subtitle command."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from src.handlers import search, subtitle_card, subtitle_search
from src.models import MediaKind, SubtitleDetails, SubtitleFile, SubtitlePack, SubtitleSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState, CardEntry, SubtitleCardEntry, SubtitleSearchEntry
from src.services.formatting import (
    subtitle_card_text,
    subtitle_pack_caption,
    subtitle_pack_keyboard,
    subtitle_results_keyboard,
    subtitle_root_keyboard,
)
from src.services.rich import rich_subtitle_message, rich_subtitle_pack_message

# --- fixtures ----------------------------------------------------------------


def _summary(i: int = 0, kind: MediaKind = MediaKind.MOVIE) -> SubtitleSummary:
    return SubtitleSummary(
        slug=f"persian-subtitle-title-{i}",
        title_en=f"Title {i}",
        year=2000 + i,
        poster_url=f"https://subkade.ir/wp-content/uploads/t{i}.webp",
        kind=kind,
        page_url=f"https://subkade.ir/persian-subtitle-title-{i}/",
    )


def _movie_details() -> SubtitleDetails:
    return SubtitleDetails(
        summary=_summary(1),
        title_fa="عنوان یک",
        imdb="8.7/10",
        plot="داستان فیلم.",
        genres=["درام", "علمی تخیلی"],
        countries=["امریکا"],
        cast=["A", "B"],
        translators="غریبی، طهماسبی",
        sync_note="هماهنگ با نسخه BluRay",
        packs=[SubtitlePack(label="فیلم", files=[SubtitleFile(label="زیرنویس فارسی فیلم", url="https://dl1.subkade.ir/a.zip")])],
    )


def _series_details() -> SubtitleDetails:
    return SubtitleDetails(
        summary=_summary(2, MediaKind.SERIES),
        title_fa="سریال دو",
        imdb="9.5/10",
        plot="داستان سریال.",
        airing=True,
        packs=[
            SubtitlePack(label="فصل 1", files=[SubtitleFile(label="زیرنویس فارسی همه قسمت‌ها", url="https://dl1.subkade.ir/s01.zip")]),
            SubtitlePack(
                label="فصل 2",
                files=[
                    SubtitleFile(label="زیرنویس فارسی قسمت 1 تا 8", url="https://dl1.subkade.ir/s02a.zip"),
                    SubtitleFile(label="زیرنویس فارسی قسمت 9 تا 16", url="https://dl1.subkade.ir/s02b.zip"),
                ],
            ),
        ],
    )


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.chat = SimpleNamespace(id=user_id)
    message.answer = AsyncMock(return_value=AsyncMock())
    message.answer_photo = AsyncMock()
    return message


def _callback(data: str) -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.from_user = User(id=42, is_bot=False, first_name="t")
    cb.message = AsyncMock(spec=Message)
    cb.message.chat = SimpleNamespace(id=42)
    cb.message.message_id = 7
    cb.message.content_type = "text"
    cb.message.edit_text = AsyncMock()
    cb.message.edit_caption = AsyncMock()
    cb.message.answer_photo = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _state() -> FSMContext:
    state = AsyncMock(spec=FSMContext)
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    return state


@pytest.fixture
def deps(tmp_path: Path) -> dict[str, Any]:
    from src.repos.db import Database

    return {
        "bot": AsyncMock(),
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "subkade": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc"),
        "state": _state(),
        "db": Database(tmp_path / "test.db"),
    }


# --- state -------------------------------------------------------------------


def test_subtitle_state_entries_do_not_cross_with_movie_entries() -> None:
    from src.models import MovieSummary

    state = CallbackState(ttl=60)
    movie_key = state.create(CardEntry(summary=MovieSummary(slug="m", title_en="M")))
    sub_key = state.create_subtitle(SubtitleCardEntry(summary=_summary()))
    search_key = state.create_subtitle_search(SubtitleSearchEntry(query="q", pairs=[]))
    assert state.get_subtitle(sub_key) is not None
    assert state.get_subtitle(movie_key) is None
    assert state.get(sub_key) is None
    assert state.get_subtitle_search(search_key) is not None
    assert state.get_search(search_key) is None
    assert state.get_subtitle_search(sub_key) is None


# --- keyboards ---------------------------------------------------------------


def test_subtitle_results_keyboard_matches_movie_pagination_layout() -> None:
    pairs = [(f"k{i:05d}", SubtitleCardEntry(summary=_summary(i))) for i in range(5)]
    kb = subtitle_results_keyboard(pairs, page=1, page_count=3, search_key="abc123")
    rows = kb.inline_keyboard
    assert len(rows) == 6
    assert rows[0][0].callback_data == "sm:k00000"
    assert rows[0][0].text == "🎬 Title 0 (2000)"
    nav = rows[-1]
    assert [b.text for b in nav] == ["◀", "2/3", "▶"]
    assert [b.callback_data for b in nav] == ["spg:abc123:0", "spg:abc123:i", "spg:abc123:2"]
    for row in rows:
        for btn in row:
            assert len(btn.callback_data.encode()) <= 64


def test_subtitle_results_keyboard_single_page_has_no_nav() -> None:
    pairs = [("k1", SubtitleCardEntry(summary=_summary(0, MediaKind.SERIES)))]
    kb = subtitle_results_keyboard(pairs, page=0, page_count=1, search_key="s")
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].text.startswith("📺")


def test_root_keyboard_single_file_movie_is_a_direct_download_button() -> None:
    kb = subtitle_root_keyboard(_movie_details(), "k1")
    first = kb.inline_keyboard[0][0]
    assert first.url == "https://dl1.subkade.ir/a.zip" and first.callback_data is None
    assert first.text.startswith("⬇")
    assert kb.inline_keyboard[-1][0].url == "https://subkade.ir/persian-subtitle-title-1/"


def test_root_keyboard_series_lists_packs_then_pack_keyboard_lists_files() -> None:
    details = _series_details()
    kb = subtitle_root_keyboard(details, "k2")
    texts = [row[0].text for row in kb.inline_keyboard]
    assert texts[0].endswith("فصل 1") and "2 فایل" in texts[1]
    assert kb.inline_keyboard[0][0].callback_data == "sp:k2:0"
    assert kb.inline_keyboard[1][0].callback_data == "sp:k2:1"
    pack_kb = subtitle_pack_keyboard(details.packs[1], "k2")
    assert [b.url for row in pack_kb.inline_keyboard[:-1] for b in row] == [
        "https://dl1.subkade.ir/s02a.zip",
        "https://dl1.subkade.ir/s02b.zip",
    ]
    assert pack_kb.inline_keyboard[-1][0].callback_data == "sx:k2"


def test_classic_texts_contain_metadata_and_links() -> None:
    text = subtitle_card_text(_movie_details())
    assert "Title 1" in text and "عنوان یک" in text and "8.7/10" in text
    assert "غریبی" in text and "BluRay" in text and "1 فایل" in text
    series = _series_details()
    assert "در حال پخش" in subtitle_card_text(series)
    caption = subtitle_pack_caption(series, series.packs[1])
    assert 'href="https://dl1.subkade.ir/s02a.zip"' in caption and "2 فایل" in caption


# --- rich ---------------------------------------------------------------------


def _blocks(rich) -> list[dict]:
    return rich.model_dump(exclude_none=True)["blocks"]


def test_rich_subtitle_message_has_poster_info_table_story_and_packs_table() -> None:
    rich = rich_subtitle_message(_series_details())
    assert rich.is_rtl is True
    types = [b["type"] for b in _blocks(rich)]
    assert types == ["photo", "table", "divider", "pullquote", "divider", "heading", "table"]
    info, packs = (b for b in _blocks(rich) if b["type"] == "table")
    assert info["cells"][0][0]["text"] == "Title 2 (2002)" and info["cells"][0][1]["text"] == "سریال دو"
    # header + 3 files (one row per file, labelled by pack)
    assert len(packs["cells"]) == 4
    assert packs["cells"][2][0]["text"] == "فصل 2"
    link = packs["cells"][2][2]["text"]
    assert isinstance(link, dict) and link["url"] == "https://dl1.subkade.ir/s02a.zip"


def test_rich_subtitle_message_without_poster_or_plot() -> None:
    details = _movie_details()
    details.summary.poster_url = None
    details.plot = None
    types = [b["type"] for b in _blocks(rich_subtitle_message(details))]
    assert types == ["table", "divider", "heading", "table"]


def test_rich_pack_message_lists_pack_files() -> None:
    details = _series_details()
    rich = rich_subtitle_pack_message(details, details.packs[1])
    blocks = _blocks(rich)
    assert blocks[0]["type"] == "heading" and "فصل 2" in blocks[0]["text"]
    assert len(blocks[1]["cells"]) == 3


# --- handlers: search + pagination --------------------------------------------


async def test_button_and_command_arm_listening_state() -> None:
    state = _state()
    cb = _callback("srch:sub_go")
    await subtitle_search.begin_subtitle_search(cb, state)
    state.set_state.assert_awaited_once_with(subtitle_search.SubtitleSearchStates.listening)
    cb.message.edit_text.assert_awaited_once_with(subtitle_search.LISTENING_TEXT)
    state = _state()
    message = _message("/subtitle")
    await subtitle_search.subtitle_command(message, state)
    state.set_state.assert_awaited_once_with(subtitle_search.SubtitleSearchStates.listening)
    message.answer.assert_awaited_once_with(subtitle_search.LISTENING_TEXT)


async def test_search_pages_results_five_per_page(deps: dict[str, Any]) -> None:
    deps["subkade"].search = AsyncMock(return_value=[_summary(i) for i in range(12)])
    message = _message("title")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    sent = message.answer.await_args
    assert search.SEARCHING_TEXT in sent.args[0]
    status.edit_text.assert_awaited_once()
    header, kwargs = status.edit_text.await_args.args[0], status.edit_text.await_args.kwargs
    assert header == "زیرنویس‌های «title» — نمایش 1–5 از 12:"
    rows = kwargs["reply_markup"].inline_keyboard
    assert len(rows) == 6 and [b.text for b in rows[-1]] == ["1/3", "▶"]
    deps["state"].clear.assert_awaited_once()
    assert await deps["cache"].get("sub:search:title") is not None

    # flip to the last page through the callback
    search_key = rows[-1][1].callback_data.split(":")[1]
    cb = _callback(f"spg:{search_key}:2")
    await subtitle_search.change_subtitle_page(cb, card_state=deps["card_state"], cfg=deps["cfg"])
    text = cb.message.edit_text.await_args.args[0]
    assert text == "زیرنویس‌های «title» — نمایش 11–12 از 12:"
    rows = cb.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert len(rows) == 3 and [b.text for b in rows[-1]] == ["◀", "3/3"]

    # indicator and out-of-range pages are no-ops
    for value in ("i", "9", "x"):
        cb = _callback(f"spg:{search_key}:{value}")
        await subtitle_search.change_subtitle_page(cb, card_state=deps["card_state"], cfg=deps["cfg"])
        cb.message.edit_text.assert_not_awaited()
        cb.answer.assert_awaited_once_with()


async def test_search_uses_cache_and_reports_no_results(deps: dict[str, Any]) -> None:
    await deps["cache"].set("sub:search:cached", [_summary(0)], ttl=60)
    deps["subkade"].search = AsyncMock()
    message = _message("Cached")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    deps["subkade"].search.assert_not_awaited()
    message.answer.assert_awaited_once()  # results directly, no loading message
    assert message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.startswith("sm:")

    deps["subkade"].search = AsyncMock(return_value=[])
    message = _message("nothing")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    message.answer.return_value.edit_text.assert_awaited_once_with(subtitle_search.NO_RESULTS_TEXT)


async def test_expired_page_key_alerts() -> None:
    cb = _callback("spg:dead00:1")
    await subtitle_search.change_subtitle_page(cb, card_state=CallbackState(ttl=60), cfg=Config(_env_file=None, bot_token="1:abc"))
    cb.answer.assert_awaited_once_with(subtitle_search.EXPIRED_TEXT, show_alert=True)


# --- handlers: card -----------------------------------------------------------


async def test_open_card_sends_rich_message_and_caches_page(deps: dict[str, Any]) -> None:
    details = _series_details()
    deps["subkade"].subtitle = AsyncMock(return_value=details)
    entry = SubtitleCardEntry(summary=details.summary)
    key = deps["card_state"].create_subtitle(entry)
    cb = _callback(f"sm:{key}")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in ("bot", "subkade", "cache", "card_state", "cfg")})  # type: ignore[arg-type]
    deps["bot"].send_rich_message.assert_awaited_once()
    kwargs = deps["bot"].send_rich_message.await_args.kwargs
    assert kwargs["chat_id"] == 42 and kwargs["rich_message"].is_rtl is True
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"sp:{key}:0"
    assert entry.rich is True and entry.details is details
    assert await deps["cache"].get(f"sub:page:{details.summary.slug}") is details

    # second open hits the cache
    deps["subkade"].subtitle = AsyncMock()
    await subtitle_card.open_subtitle_card(_callback(f"sm:{key}"), **{k: deps[k] for k in ("bot", "subkade", "cache", "card_state", "cfg")})  # type: ignore[arg-type]
    deps["subkade"].subtitle.assert_not_awaited()


async def test_open_card_falls_back_to_photo_then_text(deps: dict[str, Any]) -> None:
    details = _movie_details()
    deps["subkade"].subtitle = AsyncMock(return_value=details)
    deps["bot"].send_rich_message = AsyncMock(side_effect=TelegramBadRequest(method=AsyncMock(), message="Bad Request: RICH_MESSAGE_INVALID"))
    entry = SubtitleCardEntry(summary=details.summary)
    key = deps["card_state"].create_subtitle(entry)
    cb = _callback(f"sm:{key}")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in ("bot", "subkade", "cache", "card_state", "cfg")})  # type: ignore[arg-type]
    cb.message.answer_photo.assert_awaited_once()
    caption = cb.message.answer_photo.await_args.kwargs["caption"]
    assert "Title 1" in caption and entry.rich is False

    cb = _callback(f"sm:{key}")
    cb.message.answer_photo = AsyncMock(side_effect=TelegramBadRequest(method=AsyncMock(), message="Bad Request: wrong file"))
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in ("bot", "subkade", "cache", "card_state", "cfg")})  # type: ignore[arg-type]
    cb.message.edit_text.assert_awaited_once()
    assert cb.message.edit_text.await_args.kwargs["parse_mode"] == "HTML"


async def test_pack_and_back_edit_the_same_message(deps: dict[str, Any]) -> None:
    details = _series_details()
    entry = SubtitleCardEntry(summary=details.summary, details=details, rich=True)
    key = deps["card_state"].create_subtitle(entry)
    cb = _callback(f"sp:{key}:1")
    await subtitle_card.open_subtitle_pack(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
    deps["bot"].edit_message_text.assert_awaited_once()
    kwargs = deps["bot"].edit_message_text.await_args.kwargs
    assert kwargs["text"] is None and kwargs["rich_message"] is not None
    assert kwargs["reply_markup"].inline_keyboard[-1][0].callback_data == f"sx:{key}"
    assert entry.pack == 1

    cb = _callback(f"sx:{key}")
    await subtitle_card.back_to_subtitle_root(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
    assert deps["bot"].edit_message_text.await_count == 2
    assert entry.pack is None
    root_markup = deps["bot"].edit_message_text.await_args.kwargs["reply_markup"]
    assert root_markup.inline_keyboard[0][0].callback_data == f"sp:{key}:0"

    # classic (non-rich) card edits the caption/text instead
    entry.rich = False
    cb = _callback(f"sp:{key}:0")
    cb.message.content_type = "photo"
    await subtitle_card.open_subtitle_pack(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
    cb.message.edit_caption.assert_awaited_once()
    assert 'href="https://dl1.subkade.ir/s01.zip"' in cb.message.edit_caption.await_args.kwargs["caption"]


async def test_invalid_and_expired_pack_paths_alert(deps: dict[str, Any]) -> None:
    details = _series_details()
    key = deps["card_state"].create_subtitle(SubtitleCardEntry(summary=details.summary, details=details, rich=True))
    for data in (f"sp:{key}:9", f"sp:{key}:x", "sp:only"):
        cb = _callback(data)
        await subtitle_card.open_subtitle_pack(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
        cb.answer.assert_awaited_once_with(subtitle_card.INVALID_PATH_TEXT, show_alert=True)
    for data in ("sp:dead00:0", "sx:dead00", "sm:dead00"):
        cb = _callback(data)
        if data.startswith("sm:"):
            await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in ("bot", "subkade", "cache", "card_state", "cfg")})  # type: ignore[arg-type]
        elif data.startswith("sp:"):
            await subtitle_card.open_subtitle_pack(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
        else:
            await subtitle_card.back_to_subtitle_root(cb, bot=deps["bot"], card_state=deps["card_state"], cfg=deps["cfg"])
        cb.answer.assert_awaited_once_with(subtitle_card.EXPIRED_TEXT, show_alert=True)
    deps["bot"].edit_message_text.assert_not_awaited()
