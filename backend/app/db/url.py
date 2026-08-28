from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Libpq-style query params some managed Postgres providers (Neon, Supabase)
# include in their connection strings by default. asyncpg's SQLAlchemy
# dialect doesn't understand either one as a URL param the way psycopg2
# does -- passed through unchanged, asyncpg.connect() raises on the
# unrecognized kwarg (confirmed live: "TypeError: connect() got an
# unexpected keyword argument 'sslmode'" against a real Neon database, both
# from the app's own engine and from Alembic's separately-constructed one --
# both call this same function for that reason). TLS is expressed instead
# via connect_args={"ssl": True}, which callers apply themselves using the
# flag this returns.
_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding")
_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}


def strip_libpq_params(url: str) -> tuple[str, bool]:
    """Strips libpq-only query params from `url`, returning (cleaned_url, ssl_required)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    sslmode = (query.pop("sslmode", [None])[0] or "").lower()
    for param in _LIBPQ_ONLY_PARAMS:
        query.pop(param, None)
    cleaned = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    return cleaned, sslmode in _SSL_REQUIRED_MODES
