import asyncio
import uuid

import pytest
import redis.asyncio as redis

from app.core.rate_limit import check_token_bucket, get_redis_client

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_token_bucket_allows_up_to_capacity_then_blocks():
    key = f"test:{uuid.uuid4()}"
    for _ in range(3):
        assert await check_token_bucket(key, capacity=3, refill_per_minute=0) is True
    assert await check_token_bucket(key, capacity=3, refill_per_minute=0) is False


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time():
    key = f"test:{uuid.uuid4()}"
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is False
    await asyncio.sleep(1.1)
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True


@pytest.mark.asyncio
async def test_token_bucket_falls_back_to_in_memory_bucket_on_redis_error(monkeypatch):
    # A Redis outage/blip (including an Upstash quota rejection) must not
    # propagate and take down every gated request -- check_token_bucket
    # degrades to a real, if per-instance, in-memory token bucket rather
    # than failing open to "unlimited" (abuse traffic is exactly what you
    # don't want unleashed while Redis is already under pressure).
    client = get_redis_client()

    async def broken_eval(*args, **kwargs):
        raise redis.ConnectionError("simulated redis outage")

    monkeypatch.setattr(client, "eval", broken_eval)

    key = f"test:{uuid.uuid4()}"
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True


@pytest.mark.asyncio
async def test_in_memory_fallback_bucket_still_enforces_capacity_during_outage(monkeypatch):
    client = get_redis_client()

    async def broken_eval(*args, **kwargs):
        raise redis.ConnectionError("simulated redis outage")

    monkeypatch.setattr(client, "eval", broken_eval)

    key = f"test:{uuid.uuid4()}"
    for _ in range(2):
        assert await check_token_bucket(key, capacity=2, refill_per_minute=0) is True
    assert await check_token_bucket(key, capacity=2, refill_per_minute=0) is False


@pytest.mark.asyncio
async def test_token_bucket_falls_back_on_plain_oserror(monkeypatch):
    # Not every Redis-unavailable condition is guaranteed to already be
    # wrapped as redis.RedisError (e.g. a dropped socket can surface as a
    # raw OSError) -- the fallback must still kick in rather than crash.
    client = get_redis_client()

    async def broken_eval(*args, **kwargs):
        raise OSError("connection reset by peer")

    monkeypatch.setattr(client, "eval", broken_eval)

    key = f"test:{uuid.uuid4()}"
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True
