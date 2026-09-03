from html import escape
from typing import Any

from aiogram.enums.button_style import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.models import DownloadLink, EpisodeLink, MovieDetails, QualityPack
from src.repos.state import CardEntry

PLOT_LIMIT = 300
TELEGRAM_MESSAGE_LIMIT = 4096
EPISODE_CHUNK_LIMIT = 3800

FALLBACK_ICONS: dict[str, str] = {
    "original": "🔵",
    "dub": "🟢",
    "season": "📂",
    "quality": "⬇️",
    "result": "🎬",
}


def card_text(details: MovieDetails) -> str:
    summary = details.summary
    title = escape(summary.title_en)
    if summary.title_fa:
        title += f" — {escape(summary.title_fa)}"
    head = f"🎬 {title} ({summary.year})" if summary.year else f"🎬 {title}"
    meta_parts: list[str] = []
    if details.imdb:
        meta_parts.append(f"⭐ {escape(details.imdb)}")
    if summary.genres:
        meta_parts.append("🎭 " + escape("، ".join(summary.genres[:3])))
    lines = [head]
    if meta_parts:
        lines.append(" · ".join(meta_parts))
    if details.plot:
        plot = escape(details.plot[:PLOT_LIMIT].rsplit(" ", 1)[0]) + "…"
        lines.append(f"📄 {plot}")
    return "\n".join(lines)


def search_keyboard(
    results: list[tuple[str, CardEntry]],
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = [[_result_button(key, entry, emoji_map)] for key, entry in results]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 جستجو", callback_data="srch:go", style=ButtonStyle.PRIMARY)]
        ]
    )


def _result_button(key: str, entry: CardEntry, emoji_map: dict[str, str] | None) -> InlineKeyboardButton:
    s = entry.summary
    text = s.title_en + (f" ({s.year})" if s.year else "")
    return _icon_button(text, "result", emoji_map, callback_data=f"m:{key}", style=ButtonStyle.PRIMARY)


def root_keyboard(
    details: MovieDetails,
    key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if details.is_series:
        for idx, season in enumerate(details.seasons):
            rows.append([_icon_button(season.label, "season", emoji_map, callback_data=f"s:{key}:{idx}", style=ButtonStyle.PRIMARY)])
    elif details.has_dub:
        rows.append([
            _icon_button("دانلود با زبان اصلی", "original", emoji_map, callback_data=f"l:{key}:orig", style=ButtonStyle.PRIMARY),
            _icon_button("دانلود با دوبله فارسی", "dub", emoji_map, callback_data=f"l:{key}:dub", style=ButtonStyle.SUCCESS),
        ])
    else:
        rows = _quality_rows(details.originals, key, "orig", emoji_map)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quality_keyboard(
    links: list[DownloadLink],
    key: str,
    audio: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = _quality_rows(links, key, audio, emoji_map)
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def season_quality_keyboard(
    packs: list[QualityPack],
    key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [_icon_button(pack.quality, "quality", emoji_map, callback_data=f"q:{key}:s:{idx}", style=ButtonStyle.PRIMARY)]
        for idx, pack in enumerate(packs)
    ]
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def file_keyboard(
    links: list[DownloadLink],
    key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = [[_file_button(link)] for link in links]
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _quality_rows(
    links: list[DownloadLink],
    key: str,
    audio: str,
    emoji_map: dict[str, str] | None,
) -> list[list[InlineKeyboardButton]]:
    return [
        [_icon_button(_quality_label(link), "quality", emoji_map, callback_data=f"q:{key}:{audio}:{idx}", style=ButtonStyle.PRIMARY)]
        for idx, link in enumerate(links)
    ]


def _quality_label(link: DownloadLink) -> str:
    return f"{link.quality} - {link.size}" if link.size else link.quality


def _file_button(link: DownloadLink) -> InlineKeyboardButton:
    text = "⬇ " + (link.size or "دانلود")
    if link.host:
        text += f" — {link.host}"
    return InlineKeyboardButton(text=text, url=link.url)


def _cancel_button(key: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="انصراف", callback_data=f"x:{key}", style=ButtonStyle.DANGER)


def _icon_button(
    text: str,
    role: str,
    emoji_map: dict[str, str] | None,
    **button_kwargs: Any,
) -> InlineKeyboardButton:
    if emoji_map is None:
        return InlineKeyboardButton(text=text, **button_kwargs)
    return apply_icon(text, role, emoji_map, **button_kwargs)


def episode_line(episode: EpisodeLink) -> str:
    line = f'<a href="{escape(episode.url)}">{escape(episode.label)}</a>'
    if episode.size:
        line += f" — {escape(episode.size)}"
    return line


def episode_list_text(pack: QualityPack) -> str:
    return "\n".join(episode_line(episode) for episode in pack.episodes)


def episode_list_messages(pack: QualityPack, limit: int = EPISODE_CHUNK_LIMIT) -> list[str]:
    messages: list[str] = []
    current: list[str] = []
    length = 0
    for episode in pack.episodes:
        line = episode_line(episode)
        if current and length + len(line) + 1 > limit:
            messages.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        messages.append("\n".join(current))
    return messages


def apply_icon(text: str, role: str, emoji_map: dict[str, str], **button_kwargs: Any) -> InlineKeyboardButton:
    icon = emoji_map.get(role)
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **button_kwargs)
    return InlineKeyboardButton(text=f"{FALLBACK_ICONS.get(role, '')} {text}".strip(), **button_kwargs)
