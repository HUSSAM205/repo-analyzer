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
async def _reset_redis_client():
    # Like the database, the Redis client singleton is bound to an event
    # loop. Between tests, we must reset it so a fresh client is created
    # for the next test's loop.
    yield
    import app.core.rate_limit
    app.core.rate_limit._redis_client = None
