
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


async def test_maxsize_evicts_oldest_when_full() -> None:
    cache = TTLCache(maxsize=3)
    for key in ("a", "b", "c", "d"):
        await cache.set(key, key, ttl=60)
    assert await cache.get("a") is None
    assert [await cache.get(k) for k in ("b", "c", "d")] == ["b", "c", "d"]


async def test_maxsize_prefers_expired_entries_for_eviction() -> None:
    cache = TTLCache(maxsize=2)
    await cache.set("old", "v", ttl=-1)
    await cache.set("live1", "v", ttl=60)
    await cache.set("live2", "v", ttl=60)
    assert await cache.get("old") is None
    assert await cache.get("live1") == "v"
    assert await cache.get("live2") == "v"


async def test_overwrite_existing_key_does_not_evict() -> None:
    cache = TTLCache(maxsize=2)
    await cache.set("a", 1, ttl=60)
    await cache.set("b", 2, ttl=60)
    await cache.set("a", 3, ttl=60)
    assert await cache.get("a") == 3
    assert await cache.get("b") == 2
