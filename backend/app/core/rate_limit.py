import time
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.config import get_settings
from app.db.models import User

settings = get_settings()

_redis_client: redis.Redis | None = None

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    updated_at = now
end

local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', key, 3600)

return allowed
"""


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_token_bucket(key: str, capacity: int, refill_per_minute: int) -> bool:
    client = get_redis_client()
    refill_per_sec = refill_per_minute / 60.0
    allowed = await client.eval(_TOKEN_BUCKET_LUA, 1, key, capacity, refill_per_sec, time.time(), 1)
    return bool(allowed)


async def enforce_analyze_rate_limit(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    allowed = await check_token_bucket(
        key=f"rate_limit:analyze:{current_user.id}",
        capacity=settings.rate_limit_bucket_capacity,
        refill_per_minute=settings.rate_limit_analyze_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for repo analysis requests. Try again shortly.",
        )
    return current_user


async def enforce_chat_rate_limit(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    allowed = await check_token_bucket(
        key=f"rate_limit:chat:{current_user.id}",
        capacity=settings.rate_limit_bucket_capacity,
        refill_per_minute=settings.rate_limit_chat_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for chat messages. Try again shortly.",
        )
    return current_user
