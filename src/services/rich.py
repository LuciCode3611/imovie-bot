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
    "status": ("5416081784641168838", "📺"),
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
    add("status", "وضعیت", details.series_status.label if details.series_status else None)
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


__all__ = [
    "rich_card_message",
    "rich_episode_message",
]
