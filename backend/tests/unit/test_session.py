from app.db.session import _strip_libpq_params


def test_strip_libpq_params_leaves_a_plain_url_unchanged():
    url = "postgresql+asyncpg://user:pass@host:5432/db"
    cleaned, ssl_required = _strip_libpq_params(url)
    assert cleaned == url
    assert ssl_required is False


def test_strip_libpq_params_detects_sslmode_require_and_removes_it():
    # Neon's default connection string shape.
    url = "postgresql+asyncpg://user:pass@host/db?sslmode=require"
    cleaned, ssl_required = _strip_libpq_params(url)
    assert "sslmode" not in cleaned
    assert ssl_required is True


def test_strip_libpq_params_also_strips_channel_binding():
    # Neon sometimes includes this too -- asyncpg doesn't understand it
    # either and raises on the unrecognized connect() kwarg if left in.
    url = "postgresql+asyncpg://user:pass@host/db?sslmode=require&channel_binding=require"
    cleaned, ssl_required = _strip_libpq_params(url)
    assert "sslmode" not in cleaned
    assert "channel_binding" not in cleaned
    assert ssl_required is True


def test_strip_libpq_params_treats_disable_and_allow_as_not_requiring_ssl():
    for mode in ("disable", "allow"):
        _, ssl_required = _strip_libpq_params(f"postgresql+asyncpg://u:p@h/db?sslmode={mode}")
        assert ssl_required is False


def test_strip_libpq_params_preserves_other_query_params():
    url = "postgresql+asyncpg://user:pass@host/db?sslmode=require&application_name=repo-analyzer"
    cleaned, ssl_required = _strip_libpq_params(url)
    assert "application_name=repo-analyzer" in cleaned
    assert ssl_required is True
