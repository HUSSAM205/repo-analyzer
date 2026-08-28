import asyncio
import sys

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker, engine

# asyncpg's connection teardown is incompatible with Windows' default
# ProactorEventLoop when pytest-asyncio hands out a fresh event loop per
# test (pooled connections from a closed loop blow up on close/rollback).
# The selector loop does not have this problem.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    # pytest-asyncio gives each test function its own event loop. The
    # engine's connection pool is a module-level singleton, so pooled
    # connections must not survive past the loop that created them —
    # otherwise the next test's loop tries to reuse/close a connection
    # bound to an already-closed loop. Draining the pool here (while the
    # current test's loop is still alive) forces a fresh connection to be
    # opened on the next checkout instead.
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clear_rate_limit_keys():
    # Rate-limit token buckets (app/core/rate_limit.py) are real Redis state
    # that outlives any single test -- unlike the DB session's rollback-per-
    # test isolation, a bucket key persists (with a 1h TTL) across the whole
    # test run. Most tests share the same fallback "client IP" identity
    # (httpx's ASGITransport has no real socket, so request.client.host is a
    # fixed placeholder unless a test explicitly sets X-Forwarded-For) --
    # without clearing this between tests, unrelated tests that happen to
    # run many POST /repos/analyze or /conversations/{id}/messages calls in
    # the same file exhaust the IP bucket for every test after them,
    # regardless of which user account each one uses. Cleared before each
    # test (not just after) so a prior run's leftover state can't affect the
    # first test either.
    import app.core.rate_limit as rate_limit_module

    client = rate_limit_module.get_redis_client()
    keys = [key async for key in client.scan_iter(match="rate_limit:*")]
    if keys:
        await client.delete(*keys)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis_client():
    # Like the database, the Redis client singleton is bound to an event
    # loop. Between tests, we must reset it so a fresh client is created
    # for the next test's loop. We must also close the existing client to
    # avoid leaking connection pool resources.
    yield
    import app.core.rate_limit
    if app.core.rate_limit._redis_client is not None:
        await app.core.rate_limit._redis_client.aclose()
    app.core.rate_limit._redis_client = None


@pytest_asyncio.fixture(autouse=True)
async def _reset_llm_client_cache():
    # get_llm_client() now memoizes by settings (see llm_providers.py's
    # comment on _llm_client_cache) to stop leaking a fresh SDK/httpx
    # connection pool on every call in production. That cache is keyed on
    # settings values, so most tests never observe it (a different env var
    # naturally produces a different key) -- but resetting it here too keeps
    # test runs fully independent of call order/history regardless.
    yield
    import app.core.llm_providers as llm_providers_module
    llm_providers_module._llm_client_cache_key = None
    llm_providers_module._llm_client_cache = None


@pytest_asyncio.fixture(autouse=True)
async def _reset_arq_pool():
    # Same event-loop-binding issue as the redis rate-limit client above:
    # the ArqRedis pool is a module-level singleton wrapping a redis
    # connection pool tied to the event loop that created it. Reset it
    # after every test so the next test's loop creates a fresh pool
    # instead of reusing one bound to an already-closed loop.
    yield
    import app.core.arq_pool
    if app.core.arq_pool._pool is not None:
        await app.core.arq_pool._pool.aclose()
    app.core.arq_pool._pool = None
