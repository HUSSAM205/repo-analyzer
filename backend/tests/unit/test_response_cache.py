import redis.asyncio as redis

import app.core.response_cache as response_cache_module
from app.core.response_cache import get_cached, set_cached


class ExplodingRedis:
    async def get(self, key):
        raise redis.ConnectionError("redis is down")

    async def set(self, key, value, ex=None):
        raise redis.ConnectionError("redis is down")


class OSErrorRedis:
    async def get(self, key):
        raise OSError("connection reset by peer")

    async def set(self, key, value, ex=None):
        raise OSError("connection reset by peer")


def _reset_memory_cache():
    response_cache_module._memory_cache.clear()


async def test_set_then_get_falls_back_to_memory_when_redis_is_down(monkeypatch):
    _reset_memory_cache()
    monkeypatch.setattr(response_cache_module, "get_redis_client", lambda: ExplodingRedis())

    await set_cached("k1", "hello", ttl_seconds=60)
    assert await get_cached("k1") == "hello"


async def test_get_cached_falls_back_to_memory_on_plain_oserror(monkeypatch):
    _reset_memory_cache()
    monkeypatch.setattr(response_cache_module, "get_redis_client", lambda: OSErrorRedis())

    await set_cached("k2", "still here", ttl_seconds=60)
    assert await get_cached("k2") == "still here"


async def test_get_cached_returns_none_on_genuine_miss(monkeypatch):
    _reset_memory_cache()
    monkeypatch.setattr(response_cache_module, "get_redis_client", lambda: ExplodingRedis())

    assert await get_cached("never-set") is None
