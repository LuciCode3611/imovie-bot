import asyncio

from src.repos.cache import TTLCache


async def test_set_get_roundtrip() -> None:
    cache = TTLCache()
    await cache.set("k", [1, 2], ttl=60)
    assert await cache.get("k") == [1, 2]


async def test_expiry_returns_none() -> None:
    cache = TTLCache()
    await cache.set("k", "v", ttl=-1)
    assert await cache.get("k") is None
    assert await cache.get("k") is None  # second read also clean


async def test_missing_key() -> None:
    assert await TTLCache().get("nope") is None
