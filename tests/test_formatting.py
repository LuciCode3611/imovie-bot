from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)
from src.repos.state import CardEntry
from src.services.formatting import (
    apply_icon,
    card_text,
    episode_list_text,
    file_keyboard,
    quality_keyboard,
    results_keyboard,
    root_keyboard,
    season_quality_keyboard,
    welcome_keyboard,
)


def _details(dub: bool = False, series: bool = False) -> MovieDetails:
    summary = MovieSummary(
        slug="interstellar-2014",
        title_en="Interstellar",
        title_fa="میان‌ستاره‌ای",
        year=2014,
        genres=["درام", "علمی تخیلی"],
        kind=MediaKind.SERIES if series else MediaKind.MOVIE,
    )
    links = [
        DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv", size="2.1GB", host="dl.example.com"),
        DownloadLink(quality="720p", url="https://dl.example.com/f720.mkv", size="1.4GB", host="dl.example.com"),
        DownloadLink(quality="480p", url="https://dl.example.com/f480.mkv", size="800MB", host="dl.example.com"),
    ]
    episode = EpisodeLink(label="S01E01", url="https://dl.example.com/e01.mkv", size="300MB", host="dl.example.com")
    return MovieDetails(
        summary=summary,
        imdb="8.6",
        plot="در حالی که قحطی و گرسنگی به کره ی زمین چیره شده، گروهی از ستاره شناسان تصمیم میگیرند...",
        dubs=links[:1] if dub else [],
        originals=[] if series else links,
        seasons=[Season(label="فصل اول", qualities=[QualityPack(quality="1080p", episodes=[episode])])] if series else [],
    )


def test_card_text_contains_metadata_and_no_source() -> None:
    text = card_text(_details())
    assert "Interstellar" in text and "میان‌ستاره‌ای" in text and "2014" in text
    assert "8.6" in text and "درام" in text
    assert "zarfilm" not in text.lower() and "زرفیلم" not in text


def test_root_keyboard_dub_movie() -> None:
    kb = root_keyboard(_details(dub=True), "abc123")
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    styles = [btn.style for row in kb.inline_keyboard for btn in row]
    assert "دانلود با زبان اصلی" in texts and "دانلود با دوبله فارسی" in texts
    assert styles.__contains__("primary") and styles.__contains__("success")


def test_root_keyboard_anime_film_without_seasons_shows_qualities() -> None:
    """An anime film is tagged SERIES from its title but has no seasons; its
    download links must still be offered instead of an empty season list."""
    details = _details()
    details.summary.kind = MediaKind.SERIES
    details.seasons = []
    kb = root_keyboard(details, "abc123")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert [btn.text for btn in flat] == ["1080p - 2.1GB", "720p - 1.4GB", "480p - 800MB"]
    assert flat[0].callback_data == "q:abc123:orig:0"


def test_root_keyboard_no_dub_goes_straight_to_qualities() -> None:
    kb = root_keyboard(_details(dub=False), "abc123")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert flat[0].text == "1080p - 2.1GB"
    assert flat[0].callback_data == "q:abc123:orig:0"
    assert all(len(row) == 1 for row in kb.inline_keyboard)


def test_root_keyboard_series_shows_seasons() -> None:
    kb = root_keyboard(_details(series=True), "abc123")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert flat[0].text == "فصل اول" and flat[0].callback_data == "s:abc123:0"


def test_quality_keyboard_has_cancel() -> None:
    kb = quality_keyboard(_details().originals, "abc123", "orig")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert flat[0].text == "1080p - 2.1GB" and flat[0].style == "primary"
    cancel = flat[-1]
    assert cancel.text == "انصراف" and cancel.style == "danger" and cancel.callback_data == "x:abc123"
    assert all(len(row) == 1 for row in kb.inline_keyboard)


def test_quality_buttons_stack_vertically() -> None:
    kb = quality_keyboard(_details().originals, "abc123", "orig")
    rows = kb.inline_keyboard
    assert [len(row) for row in rows] == [1, 1, 1, 1]
    assert [row[0].text for row in rows] == ["1080p - 2.1GB", "720p - 1.4GB", "480p - 800MB", "انصراف"]
    root = root_keyboard(_details(dub=False), "abc123")
    assert [len(row) for row in root.inline_keyboard] == [1, 1, 1]


def test_file_keyboard_url_buttons() -> None:
    kb = file_keyboard(_details().originals, "abc123")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert flat[0].url == "https://dl.example.com/f.mkv"
    assert "2.1GB" in flat[0].text and "dl.example.com" in flat[0].text
    assert flat[-1].text == "انصراف"


def test_all_callback_data_within_telegram_limit() -> None:
    for kb in (root_keyboard(_details(dub=True), "abc123"), root_keyboard(_details(series=True), "abc123"),
               quality_keyboard(_details().originals, "abc123", "orig"), file_keyboard(_details().originals, "abc123")):
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode()) <= 64


def test_episode_list_text() -> None:
    pack = _details(series=True).seasons[0].qualities[0]
    text = episode_list_text(pack)
    assert '<a href="https://dl.example.com/e01.mkv">S01E01</a>' in text and "300MB" in text


def test_results_keyboard_single_page_has_no_nav() -> None:
    entry = CardEntry(summary=_details().summary)
    kb = results_keyboard([("aaaaaa", entry)], 0, 1, "skey001")
    btn = kb.inline_keyboard[0][0]
    assert btn.callback_data == "m:aaaaaa" and btn.style == "primary"
    assert len(kb.inline_keyboard) == 1


def test_results_keyboard_nav_row_covers_all_pages() -> None:
    entry = CardEntry(summary=_details().summary)
    pairs = [("aaaaaa", entry)] * 5
    first = results_keyboard(pairs, 0, 3, "skey001").inline_keyboard[-1]
    assert [b.text for b in first] == ["1/3", "▶"]
    assert first[0].callback_data == "pg:skey001:i"
    assert first[1].callback_data == "pg:skey001:1"
    middle = results_keyboard(pairs, 1, 3, "skey001").inline_keyboard[-1]
    assert [b.text for b in middle] == ["◀", "2/3", "▶"]
    assert middle[0].callback_data == "pg:skey001:0"
    last = results_keyboard(pairs, 2, 3, "skey001").inline_keyboard[-1]
    assert [b.text for b in last] == ["◀", "3/3"]
    for row in (first, middle, last):
        for btn in row:
            assert len(btn.callback_data.encode()) <= 64


def test_welcome_keyboard_single_search_button() -> None:
    kb = welcome_keyboard()
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 1
    btn = kb.inline_keyboard[0][0]
    assert btn.text == "🔍 جستجو" and btn.callback_data == "srch:go" and btn.style == "primary"
    assert btn.icon_custom_emoji_id is None


def test_apply_icon_fallback_and_custom() -> None:
    from aiogram.types import InlineKeyboardButton

    custom = apply_icon("دانلود", "dub", {"dub": "5368385512908012910"})
    assert isinstance(custom, InlineKeyboardButton) and custom.icon_custom_emoji_id == "5368385512908012910"
    fallback = apply_icon("دانلود", "dub", {})
    assert fallback.icon_custom_emoji_id is None and fallback.text.startswith("🟢")


def test_season_quality_keyboard_lists_packs_with_cancel() -> None:
    kb = season_quality_keyboard([QualityPack(quality="1080p"), QualityPack(quality="720p")], "abc123")
    rows = kb.inline_keyboard
    assert [len(row) for row in rows] == [1, 1, 1]
    flat = [btn for row in rows for btn in row]
    assert flat[0].text == "1080p" and flat[0].callback_data == "q:abc123:s:0" and flat[0].style == "primary"
    assert flat[1].text == "720p" and flat[1].callback_data == "q:abc123:s:1"
    assert flat[-1].text == "انصراف" and flat[-1].style == "danger" and flat[-1].callback_data == "x:abc123"


def test_keyboard_builders_apply_emoji_map_icons() -> None:
    emoji_map = {"original": "111", "dub": "222", "season": "333", "quality": "444", "result": "555"}
    kb = quality_keyboard(_details().originals, "abc123", "orig", emoji_map=emoji_map)
    assert kb.inline_keyboard[0][0].text == "1080p - 2.1GB" and kb.inline_keyboard[0][0].icon_custom_emoji_id == "444"
    kb = root_keyboard(_details(dub=True), "abc123", emoji_map=emoji_map)
    assert kb.inline_keyboard[0][0].text == "دانلود با زبان اصلی" and kb.inline_keyboard[0][0].icon_custom_emoji_id == "111"
    assert kb.inline_keyboard[0][1].text == "دانلود با دوبله فارسی" and kb.inline_keyboard[0][1].icon_custom_emoji_id == "222"
    kb = root_keyboard(_details(series=True), "abc123", emoji_map=emoji_map)
    assert kb.inline_keyboard[0][0].text == "فصل اول" and kb.inline_keyboard[0][0].icon_custom_emoji_id == "333"
    kb = results_keyboard([("aaaaaa", CardEntry(summary=_details().summary))], 0, 1, "skey001", emoji_map=emoji_map)
    assert kb.inline_keyboard[0][0].icon_custom_emoji_id == "555"
    kb = file_keyboard(_details().originals, "abc123", emoji_map=emoji_map)
    assert kb.inline_keyboard[0][0].url == "https://dl.example.com/f.mkv" and kb.inline_keyboard[0][0].icon_custom_emoji_id is None
    kb = results_keyboard([("aaaaaa", CardEntry(summary=_details().summary))], 0, 1, "skey001", emoji_map={})
    assert kb.inline_keyboard[0][0].icon_custom_emoji_id is None and kb.inline_keyboard[0][0].text.startswith("🎬")


def test_episode_list_messages_short_pack_is_single_message() -> None:
    from src.services.formatting import episode_list_messages

    pack = _details(series=True).seasons[0].qualities[0]
    messages = episode_list_messages(pack)
    assert len(messages) == 1
    assert "S01E01" in messages[0]


def test_episode_list_messages_chunks_long_packs() -> None:
    from src.models import EpisodeLink
    from src.services.formatting import episode_list_messages

    pack = QualityPack(
        quality="720p",
        episodes=[
            EpisodeLink(label=f"S01E{i:03d}", url=f"https://dl.example.com/episode-number-{i:03d}.mkv", size="1.4GB")
            for i in range(250)
        ],
    )
    messages = episode_list_messages(pack, limit=1000)
    assert len(messages) > 1
    assert all(len(message) <= 1000 for message in messages)
    joined = "\n".join(messages)
    assert "S01E000" in joined and "S01E249" in joined
    assert joined.count("<a href=") == 250
