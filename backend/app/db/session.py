from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.url import strip_libpq_params

settings = get_settings()

_database_url, _ssl_required = strip_libpq_params(settings.database_url)

engine = create_async_engine(
    _database_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    # Neon suspends/recycles its own compute on its own idle timers,
    # independent of this pool's own lifecycle (see keepalive's docstring in
    # main.py) -- a connection this pool has been holding open can go stale
    # on Neon's side without this process ever finding out until the next
    # query fails on it. pool_pre_ping already catches that at checkout time,
    # but recycling proactively every 5 minutes means a connection is never
    # held long enough to hit Neon's own idle-suspend window in the first
    # place. pool_timeout bounds how long a request waits for a pool slot
    # under contention -- SQLAlchemy's 30s default would let a burst of
    # concurrent requests queue for a full 30s behind a Neon cold-start
    # before failing; 10s fails faster into the pool's own real capacity
    # limit instead of masking it as a hung request.
    pool_recycle=300,
    pool_timeout=10,
    connect_args={"ssl": True} if _ssl_required else {},
)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
