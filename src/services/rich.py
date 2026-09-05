"""Bot API 10.1/10.2 rich messages.

The card ("box") for a movie/series is rendered as a single rich message:
poster block + a centered, borderless metadata table + a centered
pull-quote with the story. Episode packs reuse the same structure with a
compact table of tappable episode links.

On clients/API versions that predate rich messages, callers fall back to the
classic photo card (see src/handlers/card.py).
"""

from aiogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    InputRichBlockBlockQuotation,
    InputRichBlockDivider,
    InputRichBlockDocument,
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

from src.models import MovieDetails, QualityPack, Season, SubtitleDetails
from src.services.formatting import KIND_WORDS, kind_badge

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


# --- subtitles (SubDL API) ---------------------------------------------------


def _subtitle_info_table(details: SubtitleDetails) -> InputRichBlockTable:
    """Title / kind / seasons / file count — SubDL supplies no poster, rating or
    synopsis, and the downloads live in the buttons under the card."""
    summary = details.summary
    title = summary.title_en + (f" ({summary.year})" if summary.year else "")
    kind = f"{kind_badge(summary.kind)} {KIND_WORDS.get(summary.kind, '')}".strip()
    rows: list[list[RichBlockTableCell]] = [
        [_text_cell(title, header=True), _text_cell("زیرنویس فارسی", header=True)],
        [_cell("نوع"), _text_cell(kind)],
    ]
    if details.seasons:
        rows.append([_cell("فصل‌ها"), _text_cell("، ".join(str(season) for season in details.seasons))])
    rows.append([_cell("فایل‌ها"), _text_cell(f"{details.file_count} فایل فارسی")])
    return InputRichBlockTable(is_bordered=False, is_striped=False, is_compact=True, cells=rows)


def rich_subtitle_message(details: SubtitleDetails) -> InputRichMessage:
    """Subtitle box: the metadata table only, RTL like the movie card."""
    return InputRichMessage(blocks=[_subtitle_info_table(details)], is_rtl=True)


# --- delivering a subtitle archive -------------------------------------------

# The one instruction that travels with every delivered subtitle. It replaces
# the old per-file caption: what a user needs to know is how to *use* the zip,
# and that is the same for every title, season and episode.
SUBTITLE_UNPACK_HINT = "زیرنویس را از حالت فشرده خارج کنید و داخل مدیا پلیر اضافه کنید"


def subtitle_hint_table() -> InputRichBlockTable:
    """The instruction as a borderless, centered single-row table."""
    return InputRichBlockTable(
        is_bordered=False,
        is_striped=False,
        is_compact=True,
        cells=[[_cell(SUBTITLE_UNPACK_HINT)]],
    )


def subtitle_hint_block() -> InputRichBlockBlockQuotation:
    """The instruction inside a quote.

    A *block* quotation is the only quotation block that can nest another block
    (a pull quotation takes plain text), which is what lets the table live
    inside the quote rather than beside it.
    """
    return InputRichBlockBlockQuotation(blocks=[subtitle_hint_table()])


def rich_subtitle_document_message(document: InputMediaDocument) -> InputRichMessage:
    """One bubble: the archive itself, then the unpack instruction under it.

    The document block's own caption is ignored by Telegram, so nothing is set —
    the file name carries the title and the quote carries the instruction.
    """
    return InputRichMessage(
        blocks=[InputRichBlockDocument(document=document), subtitle_hint_block()],
        is_rtl=True,
    )


def rich_subtitle_hint_message() -> InputRichMessage:
    """The instruction on its own — the shape used when a document cannot ride
    inside a rich message (older client or API), so the note still arrives."""
    return InputRichMessage(blocks=[subtitle_hint_block()], is_rtl=True)


__all__ = [
    "rich_card_message",
    "rich_episode_message",
    "rich_subtitle_document_message",
    "rich_subtitle_hint_message",
    "rich_subtitle_message",
    "subtitle_hint_block",
    "subtitle_hint_table",
]
