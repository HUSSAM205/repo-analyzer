from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# Libpq-style query params some managed Postgres providers (Neon, Supabase)
# include in their connection strings by default. asyncpg's SQLAlchemy
# dialect doesn't understand either one as a URL param the way psycopg2
# does -- passed through unchanged, asyncpg.connect() raises on the
# unrecognized kwarg. TLS is expressed instead via connect_args={"ssl":
# True} below.
_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding")
_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}


def _strip_libpq_params(url: str) -> tuple[str, bool]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    sslmode = (query.pop("sslmode", [None])[0] or "").lower()
    for param in _LIBPQ_ONLY_PARAMS:
        query.pop(param, None)
    cleaned = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    return cleaned, sslmode in _SSL_REQUIRED_MODES


_database_url, _ssl_required = _strip_libpq_params(settings.database_url)

engine = create_async_engine(
    _database_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={"ssl": True} if _ssl_required else {},
)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
