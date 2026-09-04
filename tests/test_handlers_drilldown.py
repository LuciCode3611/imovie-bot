import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Message, User
from selectolax.parser import HTMLParser

from src.handlers import admin, card
from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)
from src.models.config import Config
from src.repos.state import CallbackState, CardEntry
from src.services.parsers import parse_movie


def _movie_details(dub: bool = True) -> MovieDetails:
    link = DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv", size="2.1GB", host="dl.example.com")
    return MovieDetails(
        summary=MovieSummary(slug="f-2014", title_en="F", kind=MediaKind.MOVIE),
        dubs=[link] if dub else [],
        originals=[link],
    )


def _series_details() -> MovieDetails:
    return MovieDetails(
        summary=MovieSummary(slug="s-2020", title_en="S", kind=MediaKind.SERIES),
        seasons=[
            Season(
                label="فصل اول",
                qualities=[
                    QualityPack(
                        quality="1080p",
                        episodes=[EpisodeLink(label="S01E01", url="https://dl.example.com/e01.mkv", size="300MB")],
                    )
                ],
            )
        ],
    )


def _cb(data: str, message: AsyncMock) -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock()
    cb.from_user = User(id=42, is_bot=False, first_name="t")
    return cb


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    message.delete = AsyncMock()
    return message


class _StubZarfilm:
    def __init__(self, session_path: Path | None = None) -> None:
        self._session_path = session_path
        self.cookies: dict[str, str] = {}
        self.ready = False

    def set_cookies(self, cookies: dict[str, str]) -> None:
        self.cookies.update(cookies)

    def persist_session(self) -> None:
        if self._session_path is not None:
            self._session_path.write_text(json.dumps(self.cookies), encoding="utf-8")

    def mark_session_ready(self) -> None:
        self.ready = True


@pytest.fixture
def deps() -> dict[str, object]:
    return {
        "bot": AsyncMock(),
        "cache": AsyncMock(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc"),
    }


async def test_language_choice_shows_qualities(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_language(_cb(f"l:{key}:dub", message), **deps)  # type: ignore[arg-type]
    message.edit_reply_markup.assert_awaited_once()
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text.endswith("1080p - 2.1GB")
    assert kb.inline_keyboard[0][0].text.startswith("⬇️")
    assert kb.inline_keyboard[0][0].callback_data == f"q:{key}:dub:0"
    assert entry.selection == "dub"


async def test_quality_choice_movie_edits_to_file_buttons(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:dub:0", message), **deps)  # type: ignore[arg-type]
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].url == "https://dl.example.com/f.mkv"


async def test_quality_choice_series_edits_rich_card(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="s:0", rich=True)
    key = deps["card_state"].create(entry)
    bot = deps["bot"]
    message = AsyncMock()
    message.chat = SimpleNamespace(id=1)
    message.message_id = 5
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    # episodes are edited into the same rich message — never as new messages
    message.answer.assert_not_awaited()
    bot.edit_message_text.assert_awaited_once()
    kw = bot.edit_message_text.await_args.kwargs
    assert kw["rich_message"] is not None
    kb = kw["reply_markup"]
    assert kb.inline_keyboard[-1][0].callback_data == f"bs:{key}:0"
    assert entry.selection == "s:0" and entry.pack == 0

    # back returns to the season quality keyboard and restores the card
    bot.edit_message_text = AsyncMock()
    await card.back_to_season(_cb(f"bs:{key}:0", message), **deps)  # type: ignore[arg-type]
    kw = bot.edit_message_text.await_args.kwargs
    assert kw["rich_message"] is not None
    back_kb = kw["reply_markup"]
    assert back_kb.inline_keyboard[0][0].callback_data == f"q:{key}:s:0"


async def test_quality_choice_series_classic_card_edits_caption(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="s:0", rich=False)
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    deps["bot"].edit_message_text.assert_not_awaited()
    message.edit_text.assert_awaited_once()
    text = message.edit_text.await_args.args[0]
    assert "S01E01" in text and "فصل اول" in text


async def test_real_series_card_drilldown_from_fixture(deps: dict[str, object]) -> None:
    fixture = Path(__file__).parent / "fixtures" / "lanterns.html"
    details = parse_movie(HTMLParser(fixture.read_text(encoding="utf-8")), "lanterns")
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=details)
    entry = CardEntry(summary=details.summary)
    key = deps["card_state"].create(entry)
    bot = deps["bot"]
    message = AsyncMock()
    message.chat = SimpleNamespace(id=1)
    message.message_id = 9
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    bot.send_rich_message.assert_awaited_once()
    sent = bot.send_rich_message.await_args.kwargs
    root_kb = sent["reply_markup"]
    assert root_kb.inline_keyboard[0][0].text.startswith("📂 فصل 1 - ")
    assert root_kb.inline_keyboard[0][0].text.endswith("قسمت")
    # the rich card contains a centered borderless table + pullquote + poster
    block_types = [b.type for b in sent["rich_message"].blocks]
    assert "table" in block_types and "pullquote" in block_types
    assert entry.rich is True

    await card.choose_season(_cb(f"s:{key}:0", message), **deps)  # type: ignore[arg-type]
    season_kw = bot.edit_message_text.await_args.kwargs
    assert season_kw["rich_message"] is not None
    assert season_kw["reply_markup"].inline_keyboard[0][0].text.endswith("1080p - 2.2 GB")

    bot.edit_message_text = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    message.answer.assert_not_awaited()
    ep_kw = bot.edit_message_text.await_args.kwargs
    rich_blocks = [b.type for b in ep_kw["rich_message"].blocks]
    assert "table" in rich_blocks
    episode_kb = ep_kw["reply_markup"]
    flat = [btn for row in episode_kb.inline_keyboard for btn in row]
    assert any("کپی" in btn.text and btn.copy_text is not None for btn in flat)
    assert flat[-1].text.startswith("🔙 بازگشت") and flat[-1].callback_data == f"bs:{key}:0"

    # back returns to the season quality keyboard
    bot.edit_message_text = AsyncMock()
    await card.back_to_season(_cb(f"bs:{key}:0", message), **deps)  # type: ignore[arg-type]
    back_kw = bot.edit_message_text.await_args.kwargs
    assert back_kw["reply_markup"].inline_keyboard[0][0].text.endswith("1080p - 2.2 GB")


async def test_cancel_returns_to_root_classic(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub", pack=1, rich=False)
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.cancel(_cb(f"x:{key}", message), **deps)  # type: ignore[arg-type]
    message.edit_text.assert_awaited_once()
    kb = message.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data == f"l:{key}:orig"
    assert entry.selection == "" and entry.pack is None


async def test_cancel_returns_to_root_rich(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub", pack=1, rich=True)
    key = deps["card_state"].create(entry)
    bot = deps["bot"]
    message = AsyncMock()
    message.chat = SimpleNamespace(id=1)
    message.message_id = 3
    await card.cancel(_cb(f"x:{key}", message), **deps)  # type: ignore[arg-type]
    bot.edit_message_text.assert_awaited_once()
    kb = bot.edit_message_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data == f"l:{key}:orig"
    assert entry.selection == "" and entry.pack is None


async def test_expired_key_alerts(deps: dict[str, object]) -> None:
    message = AsyncMock()
    cb = _cb("x:ffff00", message)
    await card.cancel(cb, **deps)  # type: ignore[arg-type]
    cb.answer.assert_awaited_once()
    assert "منقضی" in cb.answer.await_args.args[0]


async def test_season_quality_button_labels_use_pack_quality(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), rich=False)
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.choose_season(_cb(f"s:{key}:0", message), **deps)  # type: ignore[arg-type]
    # classic card: markup edit only
    kb = message.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text.endswith("1080p")
    assert kb.inline_keyboard[0][0].callback_data == f"q:{key}:s:0"


def test_parse_cookie_header_extracts_pairs() -> None:
    from src.services.parsers import parse_cookie_header

    cookies = parse_cookie_header("wordpress_logged_in_abc=user%7C1; theme=dark")
    assert cookies == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_filter_session_cookies() -> None:
    from src.services.parsers import filter_session_cookies

    kept = filter_session_cookies({"wordpress_logged_in_abc": "u", "theme": "dark"})
    assert kept == {"wordpress_logged_in_abc": "u"}


async def test_start_login_owner_only(deps: dict[str, object]) -> None:
    cfg = deps["cfg"]
    cfg.allowed_user_ids = [42]
    owner = _message("/login", user_id=42)
    fsm = AsyncMock()
    await admin.start_login(owner, fsm, cfg)  # type: ignore[arg-type]
    owner.answer.assert_awaited_once()
    fsm.set_state.assert_awaited_once()

    stranger = _message("/login", user_id=7)
    await admin.start_login(stranger, AsyncMock(), cfg)  # type: ignore[arg-type]
    stranger.answer.assert_not_awaited()


async def test_receive_cookie_updates_session_and_deletes_message(
    deps: dict[str, object], tmp_path: Path
) -> None:
    cfg = deps["cfg"]
    cfg.allowed_user_ids = [42]
    cfg.session_path = tmp_path / "session.json"

    message = _message("wordpress_logged_in_abc=user%7C1; theme=dark", user_id=42)
    fsm = AsyncMock()
    stub = _StubZarfilm(cfg.session_path)
    await admin.receive_cookie(message, fsm, cfg, stub)  # type: ignore[arg-type]
    message.delete.assert_awaited_once()
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    assert stub.ready is True
    message.answer.assert_awaited_once()
    fsm.clear.assert_awaited_once()


async def test_receive_cookie_delete_failure_still_persists_and_warns(
    deps: dict[str, object], tmp_path: Path
) -> None:
    cfg = deps["cfg"]
    cfg.session_path = tmp_path / "session.json"
    message = _message("wordpress_logged_in_abc=user%7C1", user_id=42)
    message.delete.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"), message="Bad Request: message to delete not found"
    )
    fsm = AsyncMock()
    stub = _StubZarfilm(cfg.session_path)
    await admin.receive_cookie(message, fsm, cfg, stub)  # type: ignore[arg-type]
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    texts = [call.args[0] for call in message.answer.await_args_list]
    assert admin.DELETE_FAILED_TEXT in texts
    assert texts[-1] == admin.SESSION_UPDATED_TEXT


async def test_receive_cookie_without_session_cookie_rejects(
    deps: dict[str, object], tmp_path: Path
) -> None:
    cfg = deps["cfg"]
    cfg.session_path = tmp_path / "session.json"
    message = _message("theme=dark", user_id=42)
    fsm = AsyncMock()
    stub = _StubZarfilm(cfg.session_path)
    await admin.receive_cookie(message, fsm, cfg, stub)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == admin.NO_SESSION_COOKIE_TEXT
    # a cancel/retry keyboard is attached and the FSM stays in waiting state
    assert message.answer.await_args.kwargs.get("reply_markup") is not None
    assert not cfg.session_path.exists()
    fsm.clear.assert_not_awaited()


async def test_open_card_sends_rich_message(deps: dict[str, object]) -> None:
    details = _series_details()
    entry = CardEntry(summary=details.summary)
    key = deps["card_state"].create(entry)
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=details)
    bot = deps["bot"]
    message = AsyncMock()
    message.chat = SimpleNamespace(id=777)
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    bot.send_rich_message.assert_awaited_once()
    kw = bot.send_rich_message.await_args.kwargs
    assert kw["chat_id"] == 777 and kw["rich_message"] is not None
    assert kw["reply_markup"] is not None
    # classic paths not used
    message.answer_photo.assert_not_awaited()
    assert entry.rich is True


async def test_open_card_falls_back_to_classic_when_rich_unsupported(deps: dict[str, object]) -> None:
    details = _movie_details()
    details.summary.poster_url = "https://img.example.com/poster.jpg"
    entry = CardEntry(summary=details.summary)
    key = deps["card_state"].create(entry)
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=details)
    bot = deps["bot"]
    bot.send_rich_message = AsyncMock(
        side_effect=TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="rich unsupported")
    )
    message = AsyncMock()
    message.answer_photo = AsyncMock()
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    message.answer_photo.assert_awaited_once()
    assert entry.rich is False


async def test_open_card_without_links_shows_no_links_text(deps: dict[str, object]) -> None:
    empty = MovieDetails(summary=MovieSummary(slug="f-2014", title_en="F", kind=MediaKind.MOVIE))
    entry = CardEntry(summary=empty.summary)
    key = deps["card_state"].create(entry)
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=empty)
    # rich unsupported AND no poster → edits the (search) text message
    deps["bot"].send_rich_message = AsyncMock(
        side_effect=TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="rich unsupported")
    )
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    message.edit_text.assert_awaited_once()
    text = message.edit_text.await_args.args[0]
    assert card.NO_LINKS_TEXT in text


async def test_series_quality_without_season_selection_alerts(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    cb = _cb(f"q:{key}:s:0", message)
    await card.choose_quality(cb, **deps)  # type: ignore[arg-type]
    cb.answer.assert_awaited_once()
    assert "نامعتبر" in cb.answer.await_args.args[0]
    message.answer.assert_not_awaited()


async def test_long_episode_pack_is_paginated_in_the_same_message(deps: dict[str, object]) -> None:
    episodes = [
        EpisodeLink(label=f"S01E{i:03d}", url=f"https://dl.example.com/e{i:03d}.mkv", size="1.4GB")
        for i in range(300)
    ]
    details = _series_details()
    details.seasons[0].qualities[0].episodes = episodes
    entry = CardEntry(summary=details.summary, details=details, selection="s:0", rich=False)
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    # nothing sent as new messages — the card is edited in place
    message.answer.assert_not_awaited()
    first = message.edit_text.await_args.args[0]
    assert "S01E000" in first and "S01E029" in first and "S01E299" not in first
    kb = message.edit_text.await_args.kwargs["reply_markup"]
    nav = kb.inline_keyboard[0]
    assert nav[0].callback_data == f"e:{key}:0:i"  # page indicator on page 1
    assert nav[-1].callback_data == f"e:{key}:0:1"  # next page

    # flip to the last page and confirm all episodes remain reachable
    from src.services.formatting import episode_page_count

    last_page = episode_page_count(details.seasons[0].qualities[0]) - 1
    await card.flip_episode_page(_cb(f"e:{key}:0:{last_page}", message), **deps)  # type: ignore[arg-type]
    last_text = message.edit_text.await_args.args[0]
    assert "S01E299" in last_text
    # copy buttons exist on every page and stay within CopyTextButton's limit
    for call in message.edit_text.await_args_list:
        copy_btns = [
            btn for row in call.kwargs["reply_markup"].inline_keyboard for btn in row if btn.copy_text is not None
        ]
        assert copy_btns and all(len(btn.copy_text.text) <= 256 for btn in copy_btns)


async def test_edit_not_modified_is_swallowed(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock(
        side_effect=TelegramBadRequest(
            method=SendMessage(chat_id=1, text="x"), message="Bad Request: message is not modified"
        )
    )
    cb = _cb(f"l:{key}:dub", message)
    await card.choose_language(cb, **deps)  # type: ignore[arg-type]
    cb.answer.assert_awaited_once()


async def test_malformed_callback_data_alerts_instead_of_crashing(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details())
    key = deps["card_state"].create(entry)
    cases = (
        (card.choose_language, "l:abc"),
        (card.choose_quality, "q:abc:dub:notanumber"),
        (card.choose_season, f"s:{key}:99"),
        (card.choose_quality, f"q:{key}:weird:0"),
    )
    for handler, data in cases:
        cb = _cb(data, AsyncMock())
        await handler(cb, **deps)  # type: ignore[arg-type]
        assert "نامعتبر" in cb.answer.await_args.args[0]


async def test_open_card_rich_message_contains_poster_and_buttons(deps: dict[str, object]) -> None:
    details = _movie_details()
    details.summary.poster_url = "https://img.example.com/poster.jpg"
    entry = CardEntry(summary=details.summary)
    key = deps["card_state"].create(entry)
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=details)
    bot = deps["bot"]
    message = AsyncMock()
    message.chat = SimpleNamespace(id=1)
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    bot.send_rich_message.assert_awaited_once()
    rich = bot.send_rich_message.await_args.kwargs["rich_message"]
    block_types = [getattr(b, "type", None) for b in rich.blocks]
    assert "photo" in block_types
    kb = bot.send_rich_message.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data == f"l:{key}:orig"
    message.edit_text.assert_not_awaited()


async def test_open_card_fallback_photo_failure_uses_text_card(deps: dict[str, object]) -> None:
    details = _movie_details()
    details.summary.poster_url = "https://img.example.com/broken.jpg"
    entry = CardEntry(summary=details.summary)
    key = deps["card_state"].create(entry)
    deps["cache"].get = AsyncMock(return_value=None)
    deps["zarfilm"].movie = AsyncMock(return_value=details)
    deps["bot"].send_rich_message = AsyncMock(
        side_effect=TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="rich unsupported")
    )
    message = AsyncMock()
    message.content_type = "text"
    message.answer_photo = AsyncMock(
        side_effect=TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="wrong file identifier")
    )
    message.edit_text = AsyncMock()
    await card.open_card(_cb(f"m:{key}", message), **deps)  # type: ignore[arg-type]
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.kwargs["reply_markup"] is not None


async def test_series_episode_flow_edits_photo_caption_not_new_messages(deps: dict[str, object]) -> None:
    details = _series_details()
    # classic (non-rich) photo card — episodes must edit its caption
    details.summary.poster_url = "https://img.example.com/poster.jpg"
    entry = CardEntry(summary=details.summary, details=details, selection="s:0", rich=False)
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "photo"
    message.edit_caption = AsyncMock()
    message.edit_text = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    message.answer.assert_not_awaited()
    message.edit_caption.assert_awaited_once()
    message.edit_text.assert_not_awaited()
    assert "S01E01" in message.edit_caption.await_args.kwargs["caption"]

    # paging also edits the caption
    await card.flip_episode_page(_cb(f"e:{key}:0:i", message), **deps)  # type: ignore[arg-type]
    message.edit_caption.assert_awaited_once()  # indicator press: no edit

    # back restores the card caption
    await card.back_to_season(_cb(f"bs:{key}:0", message), **deps)  # type: ignore[arg-type]
    assert message.edit_caption.await_count == 2
    back_caption = message.edit_caption.await_args.kwargs["caption"]
    assert back_caption.startswith("📺") and "S01E01" not in back_caption


async def test_series_episode_list_has_season_header(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="s:0")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.content_type = "text"
    message.edit_text = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    text = message.edit_text.await_args.args[0]
    assert text.startswith("📂")
    assert "فصل اول" in text and "قسمت" in text


async def test_trailer_button_announces_coming_soon(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details())
    key = deps["card_state"].create(entry)
    cb = _cb(f"t:{key}", AsyncMock())
    await card.send_trailer(cb, **deps)  # type: ignore[arg-type]
    cb.answer.assert_awaited_once()
    assert "به زودی اضافه میشه" in cb.answer.await_args.args[0]
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    # trailer playback must stay disabled: no video / message sent, no resolve
    cb.message.answer_video.assert_not_awaited()
    cb.message.answer.assert_not_awaited()
    deps["zarfilm"].resolve_trailer.assert_not_called()


async def test_copy_chunk_switch_keeps_single_copy_button(deps: dict[str, object]) -> None:
    from src.models import EpisodeLink, QualityPack, Season

    # 12 episodes with long URLs → multiple 256-char chunks, one copy button each
    episodes = [
        EpisodeLink(label=f"E{i:02d}", url=f"https://dl.example.com/very/long/path/episode_number_{i:02d}_quality_1080p_bluray_x265_file.mkv")
        for i in range(12)
    ]
    details = _series_details()
    details.seasons[0] = Season(label="فصل ۱", qualities=[QualityPack(quality="1080p", episodes=episodes)])
    entry = CardEntry(summary=details.summary, details=details, selection="s:0", pack=0, rich=False)
    entry.ep_page = 0
    entry.copy_chunk = 0
    key = deps["card_state"].create(entry)
    from src.services.formatting import copy_chunk_count

    total = copy_chunk_count(details.seasons[0].qualities[0])
    assert total > 1
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.switch_copy_chunk(_cb(f"cc:{key}:0:1", message), **deps)  # type: ignore[arg-type]
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    copy_buttons = [btn for row in kb.inline_keyboard for btn in row if btn.copy_text is not None]
    assert len(copy_buttons) == 1
    assert "کپی همه لینک‌ها (2/" in copy_buttons[0].text
    assert entry.copy_chunk == 1
