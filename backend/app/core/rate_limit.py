import logging
import time
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.config import get_settings
from app.db.models import User

settings = get_settings()
logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

# A Redis blip -- not a refused connection, but a hang -- must not be able to
# stall every /repos/analyze or /conversations/{id}/messages request behind
# it forever, so both the socket and the eval call below are bounded.
_REDIS_SOCKET_TIMEOUT_SECONDS = 3

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


# Broad on purpose: an Upstash quota/connection failure isn't guaranteed to
# always surface as redis.RedisError (a dropped connection can arrive as a
# raw OSError before the client wraps it), and this check must never let an
# unexpected exception shape crash a gated endpoint.
_REDIS_FAILURE_EXCEPTIONS = (redis.RedisError, OSError)

# In-process fallback token buckets, used only while Redis is unavailable.
# Rate limiting is a traffic-shaping safety net, not an auth/authz control,
# so this only needs to be "good enough per instance", not exactly as
# correct as the shared Redis bucket -- but degrading all the way to
# "unlimited" during a Redis outage/quota exhaustion is exactly the wrong
# direction (that's when abuse traffic is most likely to be adding to the
# very quota pressure causing the outage), so a real, if per-instance,
# bucket is used instead of failing open.
_MEMORY_BUCKET_MAX_ENTRIES = 2000
_memory_buckets: dict[str, tuple[float, float]] = {}


def _memory_token_bucket_check(key: str, capacity: int, refill_per_sec: float) -> bool:
    now = time.monotonic()
    tokens, updated_at = _memory_buckets.get(key, (float(capacity), now))
    tokens = min(capacity, tokens + max(0.0, now - updated_at) * refill_per_sec)
    allowed = tokens >= 1
    if allowed:
        tokens -= 1
    if key not in _memory_buckets and len(_memory_buckets) >= _MEMORY_BUCKET_MAX_ENTRIES:
        _memory_buckets.pop(next(iter(_memory_buckets)), None)
    _memory_buckets[key] = (tokens, now)
    return allowed


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
        )
    return _redis_client


async def check_token_bucket(key: str, capacity: int, refill_per_minute: int) -> bool:
    client = get_redis_client()
    refill_per_sec = refill_per_minute / 60.0
    try:
        allowed = await client.eval(_TOKEN_BUCKET_LUA, 1, key, capacity, refill_per_sec, time.time(), 1)
    except _REDIS_FAILURE_EXCEPTIONS:
        logger.warning("Redis rate-limit check failed for key=%s; using in-memory fallback bucket", key, exc_info=True)
        return _memory_token_bucket_check(key, capacity, refill_per_sec)
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
        capacity=settings.rate_limit_chat_bucket_capacity,
        refill_per_minute=settings.rate_limit_chat_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for chat messages. Try again shortly.",
        )
    return current_user


# ---------------------------------------------------------------------------
# IP-based limiting -- a second, independent gate on top of the per-user
# limits above, keyed by client IP rather than account. Per-user limiting
# alone doesn't defend against abuse from a single source spinning up many
# accounts (this app's guest-login path makes a fresh account free and
# instant) -- an IP-based ceiling catches that pattern regardless of how
# many accounts a single attacker is cycling through. Both gates run on
# every request; either one tripping is enough to reject it.
#
# Reuses the exact same Redis token-bucket primitive as the per-user limits
# (check_token_bucket) rather than adding a second rate-limiting library/
# middleware stack (e.g. slowapi) alongside it -- two independent limiting
# systems sharing one Redis instance would be harder to reason about and
# tune consistently than one mechanism applied with two different keys.
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    # Render (and most PaaS providers) terminate TLS at an edge proxy, so
    # request.client.host on the ASGI connection is that proxy's own IP, not
    # the real client's -- the actual client IP arrives via the standard
    # X-Forwarded-For header instead (proxy-appended, left-to-right,
    # client's own IP first). Falls back to request.client.host for local
    # dev / any deployment without a proxy in front, where that header is
    # simply absent.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_ip_analyze_rate_limit(request: Request) -> None:
    allowed = await check_token_bucket(
        key=f"rate_limit:ip:analyze:{_client_ip(request)}",
        capacity=settings.rate_limit_ip_analyze_bucket_capacity,
        refill_per_minute=settings.rate_limit_ip_analyze_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many analysis requests from this network. Try again shortly.",
        )


async def enforce_ip_chat_rate_limit(request: Request) -> None:
    allowed = await check_token_bucket(
        key=f"rate_limit:ip:chat:{_client_ip(request)}",
        capacity=settings.rate_limit_ip_chat_bucket_capacity,
        refill_per_minute=settings.rate_limit_ip_chat_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many chat requests from this network. Try again shortly.",
        )
