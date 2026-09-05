"""Subtitle card (SubDL title) — opened from the subtitle search results.

Rendered as a Bot API 10.1 rich message (centered metadata table), with one
inline button per Persian subtitle file. Tapping a button sends the archive
itself as a Telegram document inside a single rich message, followed by the
unpack instruction as a quoted, borderless one-row table — no download url, so
the source host and the API key both stay invisible. Clients that predate rich
messages get the plain text card, like src/handlers/card.py does for movies.

Callback prefixes (no overlap with the movie card):
    sm:{key}            open the card
    sdl:{key}:{index}   send one file as a document
"""

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaDocument, Message
from aiogram.utils.chat_action import ChatActionSender

from src.exceptions import ArchiveTooLargeError, SubdlError
from src.handlers.card import EXPIRED_TEXT
from src.handlers.subtitle_search import DISABLED_TEXT
from src.models import SubtitleFile
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.db import Database
from src.repos.state import CallbackState
from src.services.formatting import (
    SUBTITLE_DOWNLOAD_PREFIX,
    subtitle_card_text,
    subtitle_document_name,
    subtitle_link_keyboard,
    subtitle_root_keyboard,
)
from src.services.rich import (
    SUBTITLE_UNPACK_HINT,
    rich_subtitle_document_message,
    rich_subtitle_hint_message,
    rich_subtitle_message,
)
from src.services.subdl import SubdlClient

router = Router(name="subtitle_card")

NO_FILES_TEXT = "زیرنویس فارسی برای این عنوان پیدا نشد."
DOWNLOAD_FAILED_TEXT = "😅 ارسال فایل ممکن نشد؛ از لینک مستقیم دانلودش کن."
FILE_TOO_LARGE_TEXT = "⚠️ این فایل بزرگ‌تر از حدی است که ربات بتواند بفرستد؛ از لینک مستقیم دانلودش کن."


@router.callback_query(F.data.startswith("sm:"))
async def open_subtitle_card(
    callback: CallbackQuery,
    bot: Bot,
    subdl: SubdlClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    key = (callback.data or "").removeprefix("sm:")
    entry = card_state.get_subtitle(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    if not subdl.enabled:
        await callback.answer(DISABLED_TEXT, show_alert=True)
        return
    title_key = f"sub:details:{entry.summary.key}"
    details = await cache.get(title_key)
    if details is None:
        details = await subdl.details(entry.summary)
        await cache.set(title_key, details, cfg.page_ttl)
    entry.details = details
    markup = subtitle_root_keyboard(details, key, emoji_map=cfg.emoji)
    if details.packs:
        try:
            await bot.send_rich_message(
                chat_id=callback.message.chat.id,
                rich_message=rich_subtitle_message(details),
                reply_markup=markup,
            )
            entry.rich = True
            await callback.answer()
            return
        except TelegramBadRequest:
            pass  # older client/API — classic card below
    entry.rich = False
    text = subtitle_card_text(details)
    if not details.packs:
        text += f"\n\n⚠️ {NO_FILES_TEXT}"
    # a NEW message, never an edit: SubDL has no posters to send as a photo and
    # overwriting the results list would throw away the other titles
    await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith(SUBTITLE_DOWNLOAD_PREFIX))
async def download_subtitle(
    callback: CallbackQuery,
    bot: Bot,
    subdl: SubdlClient,
    card_state: CallbackState,
    db: Database,
) -> None:
    """Send one subtitle archive as a document, with the unpack instruction
    quoted underneath it in the same message.

    Preference order: a file_id this bot already uploaded (instant, and it costs
    nothing against the source's per-IP download limit) → download the public zip
    and upload it → the public link, so the user always leaves with the subtitle.
    """
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer()
        return
    _, key, raw_index = parts
    entry = card_state.get_subtitle(key)
    details = entry.details if entry is not None else None
    if details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    files = details.files
    index = int(raw_index)
    if index >= len(files):
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    file = files[index]
    # answer first: the fetch can take seconds and the spinner should not wait
    await callback.answer()
    chat_id = callback.message.chat.id

    cached = db.subtitle_file_id(file.url)
    if cached is not None:
        try:
            await _send_archive(bot, chat_id, cached)
            return
        except TelegramBadRequest:
            db.forget_subtitle_file_id(file.url)  # stale id — upload afresh below

    try:
        # the indicator covers the download AND the upload: a 20 MB archive can
        # take longer to hand to Telegram than to fetch
        async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
            archive = await subdl.fetch_archive(file.url)
            sent = await _send_archive(
                bot,
                chat_id,
                BufferedInputFile(archive.data, filename=subtitle_document_name(details, file, archive.filename)),
            )
    except ArchiveTooLargeError as exc:
        logging.info("subtitle archive too large to send: %s", exc)
        await _send_link(callback.message, file, FILE_TOO_LARGE_TEXT)
        return
    except (SubdlError, TelegramAPIError, OSError) as exc:
        logging.warning("subtitle document could not be sent, falling back to the link: %s", exc)
        await _send_link(callback.message, file, DOWNLOAD_FAILED_TEXT)
        return
    file_id = _sent_file_id(sent)
    if file_id is not None:
        db.store_subtitle_file_id(file.url, file_id)


async def _send_archive(bot: Bot, chat_id: int, document: str | BufferedInputFile) -> Message:
    """One bubble: the archive, then the unpack instruction in a quoted table.

    Media blocks inside a rich message need a recent Bot API and client, so if
    Telegram refuses the combination the file still goes out the classic way and
    the instruction follows as its own message — the user never loses the zip.
    A failure of the *document itself* (an unknown file_id, say) is re-raised so
    the caller can drop the cache entry and upload afresh.
    """
    try:
        return await bot.send_rich_message(chat_id, rich_message=rich_subtitle_document_message(InputMediaDocument(media=document)))
    except TelegramAPIError as exc:
        logging.info("could not send the document inside a rich message (%s) — sending it on its own", exc)
    sent = await bot.send_document(chat_id, document)
    await _send_unpack_hint(bot, chat_id)
    return sent


async def _send_unpack_hint(bot: Bot, chat_id: int) -> None:
    """The instruction on its own; only reached when it could not ride along."""
    try:
        await bot.send_rich_message(chat_id, rich_message=rich_subtitle_hint_message())
    except TelegramAPIError as exc:
        logging.info("rich instruction was rejected (%s) — sending it as plain text", exc)
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(chat_id, SUBTITLE_UNPACK_HINT)


def _sent_file_id(message: Message) -> str | None:
    """The uploaded archive's file_id, for the cache.

    Telegram reports a rich message's file either on the message itself or only
    inside its document block, so both shapes are accepted — without an id the
    next tap would download the same archive again.
    """
    if message.document is not None:
        return message.document.file_id
    blocks = (message.rich_message.blocks if message.rich_message is not None else None) or []
    for block in blocks:
        document = getattr(block, "document", None)
        file_id = getattr(document, "file_id", None)
        if file_id:
            return str(file_id)
    return None


async def _send_link(message: Message, file: SubtitleFile, text: str) -> None:
    """Fallback answer: the same public zip the button would have downloaded."""
    await message.answer(text, reply_markup=subtitle_link_keyboard(file))
