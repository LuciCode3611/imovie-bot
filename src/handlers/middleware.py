import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from src.repos.db import Database

BUSY_TEXT = "یه جستجو در حال اجراست؛ کمی صبر کن."
BLOCKED_TEXT = "🚫 دسترسی شما به ربات مسدود شده."


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, allowed: set[int], db: Database | None = None) -> None:
        # an empty allowlist means "open to everyone"
        self._allowed = allowed
        self._db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and self._db is not None and not user.is_bot:
            # register (or refresh) every real user, and honour blocks
            self._db.upsert_user(user.id, user.full_name, user.username)
            if self._db.is_blocked(user.id):
                logging.info("dropped update from blocked user id=%s", user.id)
                if isinstance(event, Message):
                    await event.answer(BLOCKED_TEXT)
                return None
        if self._allowed:
            if user is None or user.id not in self._allowed:
                logging.info("dropped update from unauthorized user id=%s", getattr(user, "id", None))
                return None
        return await handler(event, data)


class SearchLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        lock = self._locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            if isinstance(event, Message):
                await event.answer(BUSY_TEXT)
            return None
        async with lock:
            return await handler(event, data)
