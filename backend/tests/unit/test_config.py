from app.config import Settings


def test_database_url_upgrades_plain_postgresql_scheme_to_asyncpg():
    settings = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_upgrades_heroku_style_postgres_scheme_to_asyncpg():
    settings = Settings(database_url="postgres://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_leaves_an_already_correct_scheme_unchanged():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_feedback_recipient_email_has_a_real_default(monkeypatch):
    # Feedback submissions must have somewhere to go out of the box, not
    # just when a deployment remembers to set FEEDBACK_RECIPIENT_EMAIL --
    # see feedback_email.py's own docstring for why a misconfigured
    # recipient must never block a submission from being accepted either
    # way, but the default existing at all is what makes email delivery
    # actually happen without extra setup.
    monkeypatch.delenv("FEEDBACK_RECIPIENT_EMAIL", raising=False)
    settings = Settings()
    assert settings.feedback_recipient_email == "hossammotasem2005@gmail.com"
