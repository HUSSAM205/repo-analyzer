from app.api.routes.chat import _build_domain_context_messages
from app.db.models import Repo


def test_returns_empty_when_repo_is_none():
    assert _build_domain_context_messages(None) == []


def test_returns_empty_when_domain_briefing_is_not_set():
    repo = Repo(domain_briefing=None)
    assert _build_domain_context_messages(repo) == []


def test_builds_a_synthetic_user_assistant_exchange_from_a_real_briefing():
    repo = Repo(
        domain_briefing={
            "primary_field": "Web SaaS",
            "target_audience": "Backend engineers.",
            "architecture_overview": "A FastAPI backend talks to a Postgres database.",
        }
    )

    messages = _build_domain_context_messages(repo)

    assert len(messages) == 2
    # Anthropic (and this codebase's other providers) require the message
    # list to start with "user" -- this exchange must preserve that
    # invariant regardless of what else gets prepended in front of it.
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert "Web SaaS" in messages[1].content
    assert "Backend engineers." in messages[1].content
    assert "FastAPI backend talks to a Postgres database" in messages[1].content


def test_truncates_a_very_long_architecture_overview():
    repo = Repo(domain_briefing={"architecture_overview": "x" * 5000})

    messages = _build_domain_context_messages(repo)

    assert len(messages[1].content) < 1000


def test_returns_empty_for_a_briefing_with_only_blank_fields():
    repo = Repo(domain_briefing={"primary_field": "", "target_audience": "  ", "architecture_overview": ""})

    assert _build_domain_context_messages(repo) == []
