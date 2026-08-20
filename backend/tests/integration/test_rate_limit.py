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
async def test_token_bucket_fails_open_on_redis_error(monkeypatch):
    # A Redis outage/blip must not block every gated request forever --
    # check_token_bucket should degrade to "allowed" (fail open) rather than
    # propagate the Redis error, since rate limiting is a traffic-shaping
    # safety net, not an auth/authz control.
    client = get_redis_client()

    async def broken_eval(*args, **kwargs):
        raise redis.ConnectionError("simulated redis outage")

    monkeypatch.setattr(client, "eval", broken_eval)

    key = f"test:{uuid.uuid4()}"
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True
