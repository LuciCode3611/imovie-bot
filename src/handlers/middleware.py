import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

BUSY_TEXT = "یه جستجو در حال اجراست؛ کمی صبر کن."


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, allowed: set[int]) -> None:
        self._allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
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
