from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.types import CallbackQuery, Message, User

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
    def __init__(self) -> None:
        self._client = httpx.Client()


@pytest.fixture
def deps() -> dict[str, object]:
    return {
        "cache": AsyncMock(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(_env_file=None, bot_token="1:abc", zarfilm_username="u", zarfilm_password="p"),
    }


async def test_language_choice_shows_qualities(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_language(_cb(f"l:{key}:dub", message), **deps)  # type: ignore[arg-type]
    message.edit_reply_markup.assert_awaited_once()
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text == "1080p - 2.1GB"
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


async def test_quality_choice_series_sends_episode_list_and_reverts(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="s:0")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)  # type: ignore[arg-type]
    message.answer.assert_awaited_once()
    assert "S01E01" in message.answer.await_args.args[0]
    message.edit_reply_markup.assert_awaited_once()
    assert entry.selection == ""


async def test_cancel_returns_to_root(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.cancel(_cb(f"x:{key}", message), **deps)  # type: ignore[arg-type]
    message.edit_reply_markup.assert_awaited_once()
    assert entry.selection == ""


async def test_expired_key_alerts(deps: dict[str, object]) -> None:
    message = AsyncMock()
    cb = _cb("x:ffff00", message)
    await card.cancel(cb, **deps)  # type: ignore[arg-type]
    cb.answer.assert_awaited_once()
    assert "منقضی" in cb.answer.await_args.args[0]


async def test_season_quality_button_labels_use_pack_quality(deps: dict[str, object]) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_season(_cb(f"s:{key}:0", message), **deps)  # type: ignore[arg-type]
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text == "1080p"
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
    await admin.receive_cookie(message, fsm, cfg, _StubZarfilm())  # type: ignore[arg-type]
    message.delete.assert_awaited_once()
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    message.answer.assert_awaited_once()
    fsm.clear.assert_awaited_once()
