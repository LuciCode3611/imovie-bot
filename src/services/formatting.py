from html import escape
from typing import Any

from aiogram.enums.button_style import ButtonStyle
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    QualityPack,
    Season,
    SubtitleDetails,
    SubtitlePack,
)
from src.repos.state import CardEntry, SubtitleCardEntry

PLOT_LIMIT = 300
TELEGRAM_MESSAGE_LIMIT = 4096
EPISODE_CHUNK_LIMIT = 3800
# media captions cap at 1024 visible characters (URL entities don't count) —
# stay below it, and keep the per-page entity count well under Telegram's limit
EPISODE_CAPTION_LIMIT = 950
EPISODES_PER_PAGE = 30
# Telegram CopyTextButton accepts at most 256 characters
COPY_TEXT_LIMIT = 256

FALLBACK_ICONS: dict[str, str] = {
    "original": "🔵",
    "dub": "🟢",
    "season": "📂",
    "quality": "⬇️",
    "result": "🎬",
}

KIND_BADGES: dict[MediaKind, str] = {
    MediaKind.MOVIE: "🎬",
    MediaKind.SERIES: "📺",
}

KIND_WORDS: dict[MediaKind, str] = {
    MediaKind.MOVIE: "فیلم",
    MediaKind.SERIES: "سریال",
}


def kind_badge(kind: MediaKind) -> str:
    return KIND_BADGES.get(kind, FALLBACK_ICONS["result"])


def card_text(details: MovieDetails) -> str:
    summary = details.summary
    title = escape(summary.title_en)
    if summary.title_fa:
        title += f" — {escape(summary.title_fa)}"
    year = f" ({summary.year})" if summary.year else ""
    head = f"{kind_badge(summary.kind)} {KIND_WORDS.get(summary.kind, '')} | {title}{year}"
    meta_parts: list[str] = []
    if details.imdb:
        meta_parts.append(f"⭐ {escape(details.imdb)}")
    if details.series_status:
        meta_parts.append(f"📺 {escape(details.series_status.label)}")
    if summary.genres:
        meta_parts.append("🎭 " + escape("، ".join(summary.genres[:3])))
    lines = [head]
    if meta_parts:
        lines.append(" · ".join(meta_parts))
    if details.plot:
        plot = escape(details.plot[:PLOT_LIMIT].rsplit(" ", 1)[0]) + "…"
        lines.append(f"📄 {plot}")
    return "\n".join(lines)


def results_keyboard(
    pairs: list[tuple[str, CardEntry]],
    page: int,
    page_count: int,
    search_key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = [[_result_button(key, entry, emoji_map)] for key, entry in pairs]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"pg:{search_key}:{page - 1}"))
    if page_count > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{page_count}", callback_data=f"pg:{search_key}:i"))
    if page < page_count - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"pg:{search_key}:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def welcome_keyboard(is_owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔍 جستجو", callback_data="srch:go", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="📝 جستجوی زیرنویس", callback_data="srch:sub_go", style=ButtonStyle.SUCCESS),
        ]
    ]
    if is_owner:
        rows.append(
            [InlineKeyboardButton(text="🛠 داشبورد", callback_data="dash:open", style=ButtonStyle.PRIMARY)]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _result_button(key: str, entry: CardEntry, emoji_map: dict[str, str] | None) -> InlineKeyboardButton:
    s = entry.summary
    label = s.title_en + (f" ({s.year})" if s.year else "")
    text = f"{kind_badge(s.kind)} {label}"
    icon = (emoji_map or {}).get("result")
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, callback_data=f"m:{key}", style=ButtonStyle.PRIMARY)
    return InlineKeyboardButton(text=text, callback_data=f"m:{key}", style=ButtonStyle.PRIMARY)


def root_keyboard(
    details: MovieDetails,
    key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    # an anime film is tagged as a series by title alone and carries no
    # seasons: fall through to the movie layout so its links stay reachable
    if details.is_series and details.seasons:
        for idx, season in enumerate(details.seasons):
            label = f"{season.label} - {_season_episode_count(season)} قسمت"
            rows.append([_icon_button(label, "season", emoji_map, callback_data=f"s:{key}:{idx}", style=ButtonStyle.PRIMARY)])
    elif details.has_dub:
        rows.append([
            _icon_button("دانلود با زبان اصلی", "original", emoji_map, callback_data=f"l:{key}:orig", style=ButtonStyle.PRIMARY),
            _icon_button("دانلود با دوبله فارسی", "dub", emoji_map, callback_data=f"l:{key}:dub", style=ButtonStyle.SUCCESS),
        ])
    else:
        rows = _quality_rows(details.originals, key, "orig", emoji_map)
    if details.trailer_url:
        rows.append([
            InlineKeyboardButton(text="🎬 مشاهده تریلر", callback_data=f"t:{key}", style=ButtonStyle.PRIMARY)
        ])
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
    season_index: int | None = None,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [
            _icon_button(
                pack.quality,
                "quality",
                emoji_map,
                callback_data=f"q:{key}:s:{idx}",
                style=ButtonStyle.SUCCESS if pack.dubbed else ButtonStyle.PRIMARY,
            )
        ]
        for idx, pack in enumerate(packs)
    ]
    # back to the seasons list when this keyboard belongs to a known season,
    # otherwise just cancel to the root (defensive / legacy callers)
    rows.append([_back_to_root_button(key) if season_index is not None else _cancel_button(key)])
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
    parts = [link.quality] + ([link.size] if link.size else [])
    text = "⬇ " + " · ".join(parts)
    if link.host:
        text += f" — {link.host}"
    return InlineKeyboardButton(text=text, url=link.url)


def _cancel_button(key: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="انصراف", callback_data=f"x:{key}", style=ButtonStyle.DANGER)


def _back_to_season_button(key: str, season_index: int) -> InlineKeyboardButton:
    # the back-to-season handler (bs:) restores the card caption and shows
    # the season's quality buttons
    return InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"bs:{key}:{season_index}")


def _back_to_root_button(key: str) -> InlineKeyboardButton:
    # the cancel handler (x:) resets state and renders the root keyboard
    return InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"x:{key}")


def _season_episode_count(season: Season) -> int:
    return max((pack.episode_count for pack in season.qualities), default=0)


def episode_page_count(pack: QualityPack) -> int:
    return max(1, (len(pack.episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)


def episode_visible_line(episode: EpisodeLink) -> str:
    """The visible (non-entity) part of an episode caption line — that is what
    counts against Telegram's 1024-char caption limit, href entities do not."""
    line = episode.label
    if episode.size:
        line += f" — {episode.size}"
    return line


def episode_caption(pack: QualityPack, season: Season, page: int = 0) -> str:
    """Caption shown on the poster card while an episode pack is open."""
    header = f"📂 {escape(season.label)} · {escape(pack.quality)} — {pack.episode_count} قسمت"
    pages = episode_page_count(pack)
    if pages > 1:
        header += f"  ·  صفحه {page + 1}/{pages}"
    body: list[str] = []
    length = 0
    for episode in pack.episodes[page * EPISODES_PER_PAGE : (page + 1) * EPISODES_PER_PAGE]:
        visible = episode_visible_line(episode)
        if body and length + len(visible) + 1 > EPISODE_CAPTION_LIMIT:
            break
        body.append(episode_line(episode))
        length += len(visible) + 1
    return "\n".join([header, "", *body])


def episode_keyboard(
    pack: QualityPack,
    key: str,
    season_index: int,
    page: int = 0,
    copy_chunk: int = 0,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pages = episode_page_count(pack)
    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"e:{key}:{season_index}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=f"e:{key}:{season_index}:i"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"e:{key}:{season_index}:{page + 1}"))
        rows.append(nav)
    rows.extend(_copy_rows(pack, key, season_index, copy_chunk))
    rows.append([_back_to_season_button(key, season_index)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def copy_chunk_count(pack: QualityPack) -> int:
    """How many 256-char chunks the pack's episode links split into."""
    return max(1, len(_copy_chunks([episode.url for episode in pack.episodes])))


def _copy_rows(pack: QualityPack, key: str, season_index: int, chunk_index: int = 0) -> list[list[InlineKeyboardButton]]:
    """Exactly ONE «کپی همه لینک‌ها» CopyTextButton (Telegram caps the copied
    text at 256 chars). When the links don't fit in one chunk the button copies
    the current chunk and a «بقیه لینک‌ها ▶» switch-button steps to the next
    chunk, so every link stays reachable without ever showing a second copy
    button."""
    chunks = _copy_chunks([episode.url for episode in pack.episodes])
    if not chunks:
        return []
    chunk_index = max(0, min(chunk_index, len(chunks) - 1))
    return _copy_chunk_rows(chunks, chunk_index, key, season_index)


def _copy_chunk_rows(
    chunks: list[str],
    chunk_index: int,
    key: str,
    season_index: int,
) -> list[list[InlineKeyboardButton]]:
    total = len(chunks)
    label = "📋 کپی همه لینک‌ها" if total == 1 else f"📋 کپی همه لینک‌ها ({chunk_index + 1}/{total})"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=chunks[chunk_index]))]
    ]
    if total > 1:
        nav: list[InlineKeyboardButton] = []
        if chunk_index > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀ لینک‌های قبلی",
                    callback_data=f"cc:{key}:{season_index}:{chunk_index - 1}",
                )
            )
        if chunk_index < total - 1:
            nav.append(
                InlineKeyboardButton(
                    text="بقیه لینک‌ها ▶",
                    callback_data=f"cc:{key}:{season_index}:{chunk_index + 1}",
                )
            )
        rows.append(nav)
    return rows


def _copy_chunks(urls: list[str], limit: int = COPY_TEXT_LIMIT) -> list[str]:
    """Split URLs into newline-joined chunks that fit CopyTextButton's limit."""
    chunks: list[str] = []
    current = ""
    for url in urls:
        if not current:
            current = url
        elif len(current) + 1 + len(url) <= limit:
            current = f"{current}\n{url}"
        else:
            chunks.append(current)
            current = url
    if current:
        chunks.append(current)
    return chunks


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


def episode_list_messages(pack: QualityPack, limit: int = EPISODE_CHUNK_LIMIT, header: str = "") -> list[str]:
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
    if header and messages:
        messages[0] = f"{header}\n\n{messages[0]}"
    return messages


def apply_icon(text: str, role: str, emoji_map: dict[str, str], **button_kwargs: Any) -> InlineKeyboardButton:
    icon = emoji_map.get(role)
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **button_kwargs)
    return InlineKeyboardButton(text=f"{FALLBACK_ICONS.get(role, '')} {text}".strip(), **button_kwargs)


# --- subtitles (subkade.ir) -------------------------------------------------

SUBTITLE_PLOT_LIMIT = 260


def subtitle_results_keyboard(
    pairs: list[tuple[str, SubtitleCardEntry]],
    page: int,
    page_count: int,
    search_key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """Same layout as the movie results: one button per result plus the
    ◀ 1/3 ▶ navigation row (spg: pages, sm: opens a subtitle card)."""
    rows = [[_subtitle_result_button(key, entry, emoji_map)] for key, entry in pairs]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"spg:{search_key}:{page - 1}"))
    if page_count > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{page_count}", callback_data=f"spg:{search_key}:i"))
    if page < page_count - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"spg:{search_key}:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _subtitle_result_button(key: str, entry: SubtitleCardEntry, emoji_map: dict[str, str] | None) -> InlineKeyboardButton:
    s = entry.summary
    label = s.title_en + (f" ({s.year})" if s.year else "")
    text = f"{kind_badge(s.kind)} {label}"
    icon = (emoji_map or {}).get("result")
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, callback_data=f"sm:{key}", style=ButtonStyle.PRIMARY)
    return InlineKeyboardButton(text=text, callback_data=f"sm:{key}", style=ButtonStyle.PRIMARY)


def subtitle_root_keyboard(
    details: SubtitleDetails,
    key: str,
    emoji_map: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """Card root: a movie with a single file gets the download button right
    away; series (or multi-file posts) list their packs (seasons) first."""
    rows: list[list[InlineKeyboardButton]] = []
    if len(details.packs) == 1 and details.packs[0].file_count == 1:
        rows.append([_subtitle_file_button(details.packs[0].files[0].label, details.packs[0].files[0].url)])
    else:
        for idx, pack in enumerate(details.packs):
            label = f"{pack.label} - {pack.file_count} فایل" if pack.file_count > 1 else pack.label
            rows.append([_icon_button(label, "season", emoji_map, callback_data=f"sp:{key}:{idx}", style=ButtonStyle.PRIMARY)])
    # no source-page button: the scraped domain stays invisible to users
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subtitle_pack_keyboard(pack: SubtitlePack, key: str) -> InlineKeyboardMarkup:
    rows = [[_subtitle_file_button(file.label, file.url)] for file in pack.files]
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"sx:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# custom emoji shown on every subtitle download button
SUBTITLE_DOWNLOAD_EMOJI_ID = "5406745015365943482"


def _subtitle_file_button(label: str, url: str) -> InlineKeyboardButton:
    """Blue (primary) download button, icon included when the bot may use one."""
    text = label if label.startswith("دانلود") else f"دانلود {label}"
    return InlineKeyboardButton(
        text=text,
        url=url,
        style=ButtonStyle.PRIMARY,
        icon_custom_emoji_id=SUBTITLE_DOWNLOAD_EMOJI_ID,
    )


def subtitle_card_text(details: SubtitleDetails) -> str:
    """Classic (non-rich) subtitle card caption, HTML parse mode."""
    summary = details.summary
    title = escape(summary.title_en)
    if details.title_fa:
        title += f" — {escape(details.title_fa)}"
    year = f" ({summary.year})" if summary.year else ""
    lines = [f"📝 زیرنویس فارسی {KIND_WORDS.get(summary.kind, '')} | {title}{year}"]
    meta: list[str] = []
    if details.imdb:
        meta.append(f"⭐ {escape(details.imdb)}")
    if details.airing:
        meta.append("🟢 در حال پخش")
    if details.genres:
        meta.append("🎭 " + escape("، ".join(details.genres[:3])))
    if meta:
        lines.append(" · ".join(meta))
    if details.sync_note:
        lines.append(f"🎯 {escape(details.sync_note)}")
    if details.plot:
        plot = details.plot
        if len(plot) > SUBTITLE_PLOT_LIMIT:
            plot = plot[:SUBTITLE_PLOT_LIMIT].rsplit(" ", 1)[0] + "…"
        lines.append(f"📄 {escape(plot)}")
    if details.packs:
        count = details.file_count
        lines.append(f"📦 {count} فایل زیرنویس در {len(details.packs)} بخش" if len(details.packs) > 1 else f"📦 {count} فایل زیرنویس")
    return "\n".join(lines)


def subtitle_pack_caption(details: SubtitleDetails, pack: SubtitlePack) -> str:
    header = f"📂 {escape(details.summary.title_en)} · {escape(pack.label)} — {pack.file_count} فایل"
    body = [f'<a href="{escape(file.url)}">{escape(file.label)}</a>' for file in pack.files]
    return "\n".join([header, "", *body])
