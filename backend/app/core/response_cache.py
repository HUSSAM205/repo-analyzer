"""Redis read-through cache for expensive, repo-scoped GET responses
(flagship tools: docs, security scan, health score, quiz, flow map, tech
debt, compliance scan).

This sits IN FRONT OF, not instead of, each tool's existing permanent
Postgres cache (Repo.readme_doc etc.) -- Postgres remains the durable
source of truth (never expires, survives a Redis flush/restart/outage
untouched) while Redis absorbs the read traffic for a "hot" repo (many
concurrent visitors viewing the same popular/trending analysis) without a
Postgres round-trip on every single request. A 24h TTL, not "forever": if
this cache is ever wrong or stale relative to Postgres for some reason
(manual DB correction, a future re-analysis feature), it self-heals within
a day rather than needing an explicit invalidation step.
"""

import logging
import time

import redis.asyncio as redis

from app.core.rate_limit import get_redis_client

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60

# In-process fallback used when Redis itself is unreachable or rejecting
# commands (connection refused, timeout, or an Upstash quota/command-limit
# error surfaced as a RESP error reply) -- these are all indistinguishable
# from this module's point of view, so any of them degrades to this cache
# rather than to "always recompute". It only helps repeat requests landing
# on the same process/dyno (no cross-instance sharing like real Redis), but
# that's still strictly better than paying the full recompute cost on every
# request for as long as Redis stays unavailable. Bounded so a prolonged
# outage can't grow this into an unbounded memory leak.
_MEMORY_CACHE_MAX_ENTRIES = 500
_memory_cache: dict[str, tuple[str, float]] = {}

# Broad on purpose: a quota/connection failure from Upstash isn't guaranteed
# to always surface as redis.RedisError (e.g. a dropped connection can
# arrive as a raw OSError before the client wraps it), and every use of this
# cache must degrade gracefully rather than propagate, so any exception here
# is treated as "Redis is unavailable right now."
_REDIS_FAILURE_EXCEPTIONS = (redis.RedisError, OSError)


def _memory_get(key: str) -> str | None:
    entry = _memory_cache.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        _memory_cache.pop(key, None)
        return None
    return value


def _memory_set(key: str, value: str, ttl_seconds: int) -> None:
    if key not in _memory_cache and len(_memory_cache) >= _MEMORY_CACHE_MAX_ENTRIES:
        # Best-effort fallback, not a durable cache -- evicting an arbitrary
        # entry to bound memory use is fine, exact policy doesn't matter.
        _memory_cache.pop(next(iter(_memory_cache)), None)
    _memory_cache[key] = (value, time.monotonic() + ttl_seconds)


async def get_cached(key: str) -> str | None:
    """Returns the cached raw value for `key`, or None on a genuine miss.
    Falls back to an in-process cache when Redis itself is unreachable, so a
    Redis outage degrades to "as if Redis were merely slow/small" rather
    than straight to "always recompute" for every request on this process.
    """
    client = get_redis_client()
    try:
        value = await client.get(key)
    except _REDIS_FAILURE_EXCEPTIONS:
        logger.warning("Redis cache read failed for key=%s; falling back to in-memory cache", key, exc_info=True)
        return _memory_get(key)
    return value if value is not None else _memory_get(key)


async def set_cached(key: str, value: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    """Best-effort write -- never raises. Always populates the in-memory
    fallback too (cheap, and keeps it warm for the moment Redis does fail),
    then best-effort mirrors to Redis so other processes/instances benefit.
    A failed Redis write must not fail the request that already has a
    perfectly good result to return; it just means the next request on
    another process pays the same (already-tolerated) cost this one did.
    """
    _memory_set(key, value, ttl_seconds)
    client = get_redis_client()
    try:
        await client.set(key, value, ex=ttl_seconds)
    except _REDIS_FAILURE_EXCEPTIONS:
        logger.warning("Redis cache write failed for key=%s; kept in-memory fallback only", key, exc_info=True)
