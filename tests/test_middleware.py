import asyncio
from unittest.mock import AsyncMock

from aiogram.types import Message, User

from src.handlers.middleware import AllowlistMiddleware, SearchLockMiddleware


def _message(user_id: int) -> Message:
    message = AsyncMock(spec=Message)
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    return message


def _data(user_id: int) -> dict:
    return {"event_from_user": User(id=user_id, is_bot=False, first_name="t")}


async def test_allowlisted_user_passes() -> None:
    handler = AsyncMock(return_value="ok")
    mw = AllowlistMiddleware(allowed={42})
    result = await mw(handler, _message(42), _data(42))
    assert result == "ok"
    handler.assert_awaited_once()


async def test_stranger_blocked() -> None:
    handler = AsyncMock()
    message = _message(7)
    mw = AllowlistMiddleware(allowed={42})
    result = await mw(handler, message, _data(7))
    assert result is None
    handler.assert_not_awaited()
    message.answer.assert_not_awaited()


async def test_missing_user_blocked_silently() -> None:
    handler = AsyncMock()
    mw = AllowlistMiddleware(allowed={42})
    result = await mw(handler, _message(42), {})
    assert result is None
    handler.assert_not_awaited()


async def test_second_concurrent_search_blocked() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(event, data):
        started.set()
        await release.wait()
        return "done"

    mw = SearchLockMiddleware()
    first = asyncio.create_task(mw(slow_handler, _message(42), _data(42)))
    await started.wait()
    handler2 = AsyncMock()
    result = await mw(handler2, _message(42), _data(42))
    assert result is None
    handler2.assert_not_awaited()
    release.set()
    assert await first == "done"


async def test_different_users_do_not_block_each_other() -> None:
    mw = SearchLockMiddleware()
    handler = AsyncMock(return_value="ok")
    held = mw._locks.setdefault(1, asyncio.Lock())
    await held.acquire()
    assert await mw(handler, _message(2), _data(2)) == "ok"
