"""Subtitle system (SubDL): models/state, keyboards, rich builders and the
handlers (search → pagination → card → public zip buttons), the /subtitle
command and the owner dashboard counters."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums.button_style import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from src.handlers import admin, search, subtitle_card, subtitle_search
from src.handlers.admin_views import overview_rich, overview_text
from src.models import MediaKind, SubtitleDetails, SubtitleFile, SubtitlePack, SubtitleSummary
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.db import Database
from src.repos.state import CallbackState, CardEntry, SubtitleCardEntry, SubtitleSearchEntry
from src.services.formatting import (
    BUTTON_TEXT_LIMIT,
    SUBTITLE_DOWNLOAD_EMOJI_ID,
    subtitle_card_text,
    subtitle_results_keyboard,
    subtitle_root_keyboard,
)
from src.services.rich import rich_subtitle_message
from src.services.subdl import SubdlClient

DOWNLOAD = "https://dl.subdl.com/subtitle"


# --- fixtures ----------------------------------------------------------------


def _summary(i: int = 0, kind: MediaKind = MediaKind.MOVIE) -> SubtitleSummary:
    return SubtitleSummary(
        title_en=f"Title {i}",
        kind=kind,
        year=2000 + i,
        sd_id=str(1000 + i),
        imdb_id=f"tt00000{i}",
        tmdb_id=100 + i,
    )


def _file(label: str, file_id: str, **kwargs: Any) -> SubtitleFile:
    """A file as the parser would build it: Persian label + public zip url."""
    return SubtitleFile(label=label, url=f"{DOWNLOAD}/{file_id}.zip", **kwargs)


def _movie_details() -> SubtitleDetails:
    return SubtitleDetails(
        summary=_summary(1),
        packs=[
            SubtitlePack(
                label="فیلم",
                files=[_file("Interstellar.2014.1080p.BluRay", "1-2"), _file("Interstellar.2014.WEB-DL", "3-4", author="translator")],
            )
        ],
    )


def _series_details() -> SubtitleDetails:
    return SubtitleDetails(
        summary=_summary(2, MediaKind.SERIES),
        packs=[
            SubtitlePack(label="فصل 1", files=[_file("همه قسمت‌ها · Breaking.Bad.S01", "s01", season=1, full_season=True)]),
            SubtitlePack(
                label="فصل 2",
                files=[
                    _file("قسمت 1–8 · Breaking.Bad.S02.Part1", "s02a", season=2, episode_from=1, episode_end=8),
                    _file("قسمت 9–13 · Breaking.Bad.S02.Part2", "s02b", season=2, episode_from=9, episode_end=13),
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
    cb.message.answer = AsyncMock()
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
    return {
        "bot": AsyncMock(),
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "subdl": AsyncMock(enabled=True),
        "cfg": Config(_env_file=None, bot_token="1:abc", subdl_api_key="k"),
        "state": _state(),
        "db": Database(tmp_path / "test.db"),
    }


CARD_DEPS = ("bot", "subdl", "cache", "card_state", "cfg")


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


def test_details_expose_file_and_season_counts() -> None:
    series = _series_details()
    assert series.file_count == 3 and series.seasons == [1, 2]
    assert series.season_labels == ["فصل 1", "فصل 2"]
    movie = _movie_details()
    assert movie.file_count == 2 and movie.seasons == [] and movie.season_labels == []


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


def test_a_very_long_title_is_capped_to_the_button_limit() -> None:
    entry = SubtitleCardEntry(summary=_summary(0).model_copy(update={"title_en": "X" * 200}))
    button = subtitle_results_keyboard([("k1", entry)], page=0, page_count=1, search_key="s").inline_keyboard[0][0]
    assert len(button.text) == BUTTON_TEXT_LIMIT and button.text.endswith("…")


def test_root_keyboard_turns_every_file_into_a_public_zip_button() -> None:
    kb = subtitle_root_keyboard(_movie_details())
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert [b.url for b in buttons] == [f"{DOWNLOAD}/1-2.zip", f"{DOWNLOAD}/3-4.zip"]
    for button in buttons:
        # every button downloads: no callback, no API key in the url
        assert button.callback_data is None
        assert "api_key" not in button.url and button.url.startswith("https://dl.subdl.com/")
        assert button.style == ButtonStyle.PRIMARY
        assert button.icon_custom_emoji_id == SUBTITLE_DOWNLOAD_EMOJI_ID
        assert button.text.startswith("دانلود")
        assert len(button.text) <= BUTTON_TEXT_LIMIT


def test_root_keyboard_names_the_season_when_there_are_several() -> None:
    rows = subtitle_root_keyboard(_series_details()).inline_keyboard
    assert [b.text for row in rows for b in row] == [
        "دانلود فصل 1 · همه قسمت‌ها · Breaking.Bad.S01",
        "دانلود فصل 2 · قسمت 1–8 · Breaking.Bad.S02.Part1",
        "دانلود فصل 2 · قسمت 9–13 · Breaking.Bad.S02.Part2",
    ]


def test_root_keyboard_truncates_a_long_release_name_instead_of_failing() -> None:
    long_name = "Some.Movie.2024.2160p.UHD.BluRay.x265.10bit.HDR.DTS-HD.MA.5.1-GROUP"
    details = _movie_details()
    details.packs[0].files[0].label = long_name  # what the parser hands over, pre-truncated
    button = subtitle_root_keyboard(details).inline_keyboard[0][0]
    assert len(button.text) == BUTTON_TEXT_LIMIT and button.text.endswith("…")


def test_root_keyboard_is_none_without_files() -> None:
    """Telegram rejects a markup with no buttons — the card then sends text only."""
    assert subtitle_root_keyboard(SubtitleDetails(summary=_summary())) is None


# --- card texts --------------------------------------------------------------


def test_classic_text_shows_title_kind_and_file_count() -> None:
    text = subtitle_card_text(_movie_details())
    assert text.splitlines()[0] == "📝 زیرنویس فارسی فیلم | Title 1 (2001)"
    assert "2 فایل زیرنویس" in text

    series_text = subtitle_card_text(_series_details())
    assert "📺" not in series_text.splitlines()[0] and "سریال" in series_text.splitlines()[0]
    assert "📂 فصل 1، فصل 2" in series_text
    assert "3 فایل زیرنویس در 2 بخش" in series_text


def test_classic_text_of_a_title_without_persian_subtitles() -> None:
    text = subtitle_card_text(SubtitleDetails(summary=_summary(3)))
    assert "0 فایل" not in text and "📦" not in text


# --- rich --------------------------------------------------------------------


def _blocks(rich) -> list[dict]:
    return rich.model_dump(exclude_none=True)["blocks"]


def test_rich_subtitle_message_is_a_single_rtl_metadata_table() -> None:
    rich = rich_subtitle_message(_series_details())
    assert rich.is_rtl is True
    blocks = _blocks(rich)
    assert [b["type"] for b in blocks] == ["table"]  # SubDL has no poster or synopsis
    cells = blocks[0]["cells"]
    assert cells[0][0]["text"] == "Title 2 (2002)" and cells[0][1]["text"] == "زیرنویس فارسی"
    assert cells[0][0]["is_header"] is True
    flat = [c["text"] for row in cells for c in row]
    assert "📺 سریال" in flat and "1، 2" in flat and "3 فایل فارسی" in flat
    assert "نوع" in flat and "فصل‌ها" in flat and "فایل‌ها" in flat


def test_rich_subtitle_table_skips_the_season_row_for_a_movie() -> None:
    cells = _blocks(rich_subtitle_message(_movie_details()))[0]["cells"]
    flat = [c["text"] for row in cells for c in row]
    assert "فصل‌ها" not in flat and "🎬 فیلم" in flat and "2 فایل فارسی" in flat


# --- handlers: arming --------------------------------------------------------


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


# --- handlers: search --------------------------------------------------------


async def test_search_pages_results_five_per_page(deps: dict[str, Any]) -> None:
    deps["subdl"].search = AsyncMock(return_value=[_summary(i) for i in range(12)])
    message = _message("title")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    status = message.answer.return_value
    assert search.SEARCHING_TEXT in message.answer.await_args.args[0]
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
    assert cb.message.edit_text.await_args.args[0] == "زیرنویس‌های «title» — نمایش 11–12 از 12:"
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
    deps["subdl"].search = AsyncMock()
    message = _message("Cached")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    deps["subdl"].search.assert_not_awaited()
    message.answer.assert_awaited_once()  # results directly, no loading message
    assert message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.startswith("sm:")

    deps["subdl"].search = AsyncMock(return_value=[])
    message = _message("nothing")
    await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    message.answer.return_value.edit_text.assert_awaited_once_with(subtitle_search.NO_RESULTS_TEXT)


async def test_search_says_so_when_the_api_key_is_missing(deps: dict[str, Any]) -> None:
    """Railway without SUBDL_API_KEY: a clear message, and no request is fired."""
    client = SubdlClient(Config(_env_file=None, bot_token="1:abc"))
    deps["subdl"] = client
    message = _message("dune")
    try:
        await subtitle_search.handle_subtitle_search(message, **deps)  # type: ignore[arg-type]
    finally:
        await client.close()
    message.answer.assert_awaited_once_with(subtitle_search.DISABLED_TEXT)
    deps["state"].clear.assert_awaited_once()
    assert client.stats["requests"] == 0


async def test_expired_page_key_alerts() -> None:
    cb = _callback("spg:dead00:1")
    await subtitle_search.change_subtitle_page(cb, card_state=CallbackState(ttl=60), cfg=Config(_env_file=None, bot_token="1:abc"))
    cb.answer.assert_awaited_once_with(subtitle_search.EXPIRED_TEXT, show_alert=True)


# --- handlers: card ----------------------------------------------------------


async def test_open_card_sends_rich_message_and_caches_the_title(deps: dict[str, Any]) -> None:
    details = _series_details()
    deps["subdl"].details = AsyncMock(return_value=details)
    entry = SubtitleCardEntry(summary=details.summary)
    key = deps["card_state"].create_subtitle(entry)
    cb = _callback(f"sm:{key}")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    deps["bot"].send_rich_message.assert_awaited_once()
    kwargs = deps["bot"].send_rich_message.await_args.kwargs
    assert kwargs["chat_id"] == 42 and kwargs["rich_message"].is_rtl is True
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == f"{DOWNLOAD}/s01.zip"
    assert entry.rich is True and entry.details is details
    deps["subdl"].details.assert_awaited_once_with(details.summary)
    assert await deps["cache"].get(f"sub:details:{details.summary.key}") is details

    # a second open of the same title hits the cache
    deps["subdl"].details = AsyncMock()
    await subtitle_card.open_subtitle_card(_callback(f"sm:{key}"), **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    deps["subdl"].details.assert_not_awaited()


async def test_open_card_falls_back_to_a_new_text_message(deps: dict[str, Any]) -> None:
    """Old clients get a plain card — sent as a new message so the results list
    stays usable for the other titles."""
    deps["subdl"].details = AsyncMock(return_value=_movie_details())
    deps["bot"].send_rich_message = AsyncMock(side_effect=TelegramBadRequest(method=AsyncMock(), message="Bad Request: RICH_MESSAGE_INVALID"))
    key = deps["card_state"].create_subtitle(SubtitleCardEntry(summary=_movie_details().summary))
    cb = _callback(f"sm:{key}")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    cb.message.answer.assert_awaited_once()
    text = cb.message.answer.await_args.args[0]
    kwargs = cb.message.answer.await_args.kwargs
    assert "Title 1" in text and "2 فایل زیرنویس" in text
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == f"{DOWNLOAD}/1-2.zip"
    cb.message.edit_text.assert_not_awaited()
    assert deps["card_state"].get_subtitle(key).rich is False


async def test_open_card_warns_when_no_persian_subtitle_exists(deps: dict[str, Any]) -> None:
    deps["subdl"].details = AsyncMock(return_value=SubtitleDetails(summary=_summary(9)))
    key = deps["card_state"].create_subtitle(SubtitleCardEntry(summary=_summary(9)))
    cb = _callback(f"sm:{key}")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    deps["bot"].send_rich_message.assert_not_awaited()  # no rich card for an empty file list
    text = cb.message.answer.await_args.args[0]
    assert subtitle_card.NO_FILES_TEXT in text
    assert cb.message.answer.await_args.kwargs["reply_markup"] is None


async def test_open_card_with_an_expired_key_alerts(deps: dict[str, Any]) -> None:
    cb = _callback("sm:dead00")
    await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    cb.answer.assert_awaited_once_with(subtitle_card.EXPIRED_TEXT, show_alert=True)


async def test_open_card_says_so_when_the_api_key_is_missing(deps: dict[str, Any]) -> None:
    client = SubdlClient(Config(_env_file=None, bot_token="1:abc"))
    deps["subdl"] = client
    key = deps["card_state"].create_subtitle(SubtitleCardEntry(summary=_summary()))
    cb = _callback(f"sm:{key}")
    try:
        await subtitle_card.open_subtitle_card(cb, **{k: deps[k] for k in CARD_DEPS})  # type: ignore[arg-type]
    finally:
        await client.close()
    cb.answer.assert_awaited_once_with(subtitle_search.DISABLED_TEXT, show_alert=True)
    deps["bot"].send_rich_message.assert_not_awaited()


# --- owner dashboard ---------------------------------------------------------


async def test_dashboard_stats_include_the_subtitle_counters() -> None:
    zarfilm = MagicMock()
    zarfilm._restore_session.return_value = False
    zarfilm.session_ttl_seconds.return_value = 0
    zarfilm.uptime_seconds.return_value = 5
    zarfilm.stats = {"searches": 1, "movies": 2}
    subdl = MagicMock(enabled=True)
    subdl.stats = {"requests": 4, "searches": 3, "titles": 2}
    cfg = Config(_env_file=None, bot_token="t")

    stats = await admin._gather_stats(zarfilm, cfg, None, subdl)
    assert stats["sub_enabled"] is True and stats["sub_searches"] == 3 and stats["sub_titles"] == 2
    assert "📝 زیرنویس: 🟢 فعال — جستجو 3 · عنوان 2" in overview_text(stats)
    cells = [c.text for block in overview_rich(stats).blocks if hasattr(block, "cells") for row in block.cells for c in row]
    assert "📝 🟢 فعال — جستجو 3 · عنوان 2" in cells

    # a host without SUBDL_API_KEY is reported as disabled, by name
    stats = await admin._gather_stats(zarfilm, cfg, None, MagicMock(enabled=False))
    assert "SUBDL_API_KEY" in overview_text(stats)

    # the dependency stays optional: older call sites omit it
    stats = await admin._gather_stats(zarfilm, cfg)
    assert stats["sub_searches"] == 0 and stats["sub_titles"] == 0 and stats["sub_enabled"] is False
    assert "غیرفعال" in overview_text(stats)
