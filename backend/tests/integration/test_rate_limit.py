import asyncio
import uuid

import pytest

from app.core.rate_limit import check_token_bucket

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
