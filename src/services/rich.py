"""Bot API 10.1/10.2 rich messages.

The card ("box") for a movie/series is rendered as a single rich message:
poster block + a centered, borderless metadata table + a centered
pull-quote with the story. Episode packs reuse the same structure with a
compact table of tappable episode links.

On clients/API versions that predate rich messages, callers fall back to the
classic photo card (see src/handlers/card.py).
"""

from aiogram.types import (
    InputMediaPhoto,
    InputRichBlockDivider,
    InputRichBlockPhoto,
    InputRichBlockPullQuotation,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
    RichText,
    RichTextCustomEmoji,
    RichTextUrl,
)

from src.models import MovieDetails, QualityPack, Season

# rich messages cap at 32,768 chars / 500 blocks / 20 table columns — one
# episode table per pack fits comfortably.

# role -> Telegram custom-emoji id used for the metadata label cells
LABEL_EMOJI: dict[str, tuple[str, str]] = {
    # role:        (custom_emoji_id, fallback unicode alternative)
    "imdb": ("5438496463044752972", "⭐"),
    "country": ("5424972470023104089", "🌍"),
    "runtime": ("5458603043203327669", "⏱"),
    "genre": ("5397782960512444700", "🎭"),
    "cast": ("5217822164362739968", "🎬"),
}


def _cell(text: RichText, *, header: bool = False) -> RichBlockTableCell:
    return RichBlockTableCell(text=text, align="center", valign="middle", is_header=header)


def _text_cell(value: str, *, header: bool = False) -> RichBlockTableCell:
    return _cell(value, header=header)


def _label_cell(role: str, text: str) -> RichBlockTableCell:
    """A label cell with a custom emoji prepended (the id the user supplied
    per metadata role); falls back to a plain label when the role has none."""
    emoji = LABEL_EMOJI.get(role)
    if emoji is None:
        return _cell(text)
    custom_id, fallback = emoji
    return _cell([RichTextCustomEmoji(custom_emoji_id=custom_id, alternative_text=fallback), f" {text}"])


def _info_table(details: MovieDetails) -> InputRichBlockTable:
    summary = details.summary
    fa_title = summary.title_fa or summary.title_en
    # Label-first cell order — this is the layout that renders RTL (label on
    # the right) on Telegram mobile clients.
    rows: list[list[RichBlockTableCell]] = [
        [_text_cell(summary.title_en, header=True), _text_cell(fa_title, header=True)]
    ]

    def add(role: str, label: str, value: str | None) -> None:
        if value:
            rows.append([_label_cell(role, label), _text_cell(value)])

    add("imdb", "امتیاز", details.imdb)
    add("runtime", "مدت زمان", details.runtime)
    add("country", "محصول", "، ".join(details.countries) if details.countries else None)
    add("genre", "ژانر", "، ".join(summary.genres[:5]) if summary.genres else None)
    add("cast", "ستارگان", "، ".join(details.cast[:5]) if details.cast else None)
    return InputRichBlockTable(is_bordered=False, is_striped=False, is_compact=True, cells=rows)


def _story_block(details: MovieDetails) -> InputRichBlockPullQuotation | None:
    if not details.plot:
        return None
    return InputRichBlockPullQuotation(text=details.plot)


def rich_card_message(details: MovieDetails) -> InputRichMessage:
    """The info box: poster + metadata table (+ divider) + centered story."""
    blocks: list = []
    if details.summary.poster_url:
        blocks.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=details.summary.poster_url)))
    blocks.append(_info_table(details))
    story = _story_block(details)
    if story is not None:
        blocks.append(InputRichBlockDivider())
        blocks.append(story)
    return InputRichMessage(blocks=blocks, is_rtl=True)


def _episode_table(pack: QualityPack) -> InputRichBlockTable:
    cells: list[list[RichBlockTableCell]] = [
        [_text_cell("قسمت", header=True), _text_cell("حجم", header=True), _text_cell("دانلود", header=True)]
    ]
    for episode in pack.episodes:
        link = RichTextUrl(text="🔗 دریافت", url=episode.url)
        cells.append([_text_cell(episode.label), _text_cell(episode.size or "—"), _cell(link)])
    return InputRichBlockTable(is_bordered=False, is_striped=True, is_compact=True, cells=cells)


def rich_episode_message(
    pack: QualityPack,
    season: Season,
) -> InputRichMessage:
    """Episode pack: compact poster-less table of tappable links + heading."""
    heading = f"📂 {season.label} · {pack.quality} — {pack.episode_count} قسمت"
    blocks: list = [
        InputRichBlockSectionHeading(text=heading, size=2),
        _episode_table(pack),
    ]
    return InputRichMessage(blocks=blocks, is_rtl=True)


def rich_dashboard_message(stats: dict) -> InputRichMessage:
    """Owner dashboard rich message. ``stats`` keys:
    online, session_present, session_valid (bool|None), ttl (seconds|None),
    uptime (seconds|None), users, searches, movies, open_mode (bool),
    proxy (str|None)."""
    online = "🟢 آنلاین" if stats.get("online") else "🔴 آفلاین"
    if not stats.get("session_present"):
        cookie = "🔴 بدون کوکی"
    elif stats.get("session_valid") is True:
        cookie = "🟢 معتبر"
    elif stats.get("session_valid") is False:
        cookie = "🔴 منقضی شده"
    else:
        cookie = "🟡 نامشخص"

    def s(value: str, header: bool = False) -> RichBlockTableCell:
        return _cell(value, header=header)

    rows = [
        [s("وضعیت ربات", header=True), s(online)],
        [s("کوکی نشست", header=True), s(cookie)],
        [s("اعتبار باقی‌مانده", header=True), s(_persian_ttl(stats.get("ttl")) or "—")],
        [s("مدت روشن بودن", header=True), s(_persian_ttl(stats.get("uptime")) or "—")],
        [s("دسترسی کاربران", header=True), s("🔓 باز برای همه" if stats.get("open_mode") else "🔒 فقط لیست مجاز")],
        [s("پروکسی", header=True), s("🟢 فعال" if stats.get("proxy") else "—")],
        [s("جستجوها", header=True), s(f"🔍 {stats.get('searches', 0)}")],
        [s("صفحه‌های باز شده", header=True), s(f"🎬 {stats.get('movies', 0)}")],
    ]
    table = InputRichBlockTable(is_bordered=False, is_compact=True, cells=rows)
    return InputRichMessage(
        blocks=[InputRichBlockSectionHeading(text="🛠 داشبورد مدیریت ربات", size=2), table],
        is_rtl=True,
    )


def _persian_ttl(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    days, rem = divmod(int(seconds), 86400)
    hours = rem // 3600
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if not parts:
        return f"{int(seconds) // 60} دقیقه"
    return " و ".join(parts)


__all__ = [
    "rich_card_message",
    "rich_dashboard_message",
    "rich_episode_message",
]
