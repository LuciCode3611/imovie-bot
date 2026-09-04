"""Bot API 10.1/10.2 rich messages.

The card ("box") for a movie/series is rendered as a single rich message:
poster block + a centered, borderless metadata table + a centered
pull-quote with the story. Episode packs reuse the same structure with a
compact bordered table of tappable episode links.

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
    RichTextUrl,
)

from src.models import MovieDetails, QualityPack, Season
from src.services.formatting import KIND_WORDS, kind_badge

# rich messages cap at 32,768 chars / 500 blocks / 20 table columns — one
# episode table per pack fits comfortably, so episodes are NOT paginated here.


def _cell(text: RichText, *, header: bool = False) -> RichBlockTableCell:
    return RichBlockTableCell(text=text, align="center", valign="middle", is_header=header)


def _text_cell(value: str, *, header: bool = False) -> RichBlockTableCell:
    return _cell(value, header=header)


def _info_table(details: MovieDetails) -> InputRichBlockTable:
    summary = details.summary
    rows: list[list[RichBlockTableCell]] = [
        [_text_cell(summary.title_en, header=True), _text_cell(summary.title_fa or "—", header=True)]
    ]
    if summary.year:
        rows.append([_text_cell("سال"), _text_cell(str(summary.year))])
    if details.countries:
        rows.append([_text_cell("محصول"), _text_cell("، ".join(details.countries))])
    runtime = _runtime(details)
    if runtime:
        rows.append([_text_cell("مدت زمان"), _text_cell(runtime)])
    if summary.genres:
        rows.append([_text_cell("ژانر"), _text_cell("، ".join(summary.genres[:5]))])
    if details.imdb:
        rows.append([_text_cell("⭐ IMDb"), _text_cell(details.imdb)])
    if details.is_series and details.seasons:
        rows.append(
            [_text_cell("فصل‌ها"), _text_cell(f"{len(details.seasons)} فصل")]
        )
    return InputRichBlockTable(is_bordered=False, is_striped=False, is_compact=True, cells=rows)


def _runtime(_details: MovieDetails) -> str | None:
    # the source page does not currently expose runtime in the parsed markup;
    # reserved so the row appears as soon as the parser provides it
    return None


def _story_block(details: MovieDetails) -> InputRichBlockPullQuotation | None:
    if not details.plot:
        return None
    return InputRichBlockPullQuotation(text=details.plot)


def rich_card_message(details: MovieDetails) -> InputRichMessage:
    """The info box: poster + metadata table (+ divider) + centered story."""
    blocks: list = []
    if details.summary.poster_url:
        blocks.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=details.summary.poster_url)))
    heading = f"{kind_badge(details.summary.kind)} {KIND_WORDS.get(details.summary.kind, '')}".strip()
    blocks.append(InputRichBlockSectionHeading(text=heading, size=2))
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
        cells.append(
            [
                _text_cell(episode.label),
                _text_cell(episode.size or "—"),
                _cell(link),
            ]
        )
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
