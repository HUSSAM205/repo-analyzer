import uuid

import pytest

from app.core.deterministic_answer import _extract_keywords, build_deterministic_answer
from app.db.models import File, Repo, RepoStatus, User
from app.db.session import async_session_maker


async def _create_repo_with_files(files: list[File]) -> uuid.UUID:
    async with async_session_maker() as db:
        user = User(email=f"det-answer-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        repo = Repo(
            user_id=user.id, url=f"https://github.com/example/det-answer-{uuid.uuid4()}", name="repo",
            status=RepoStatus.READY,
        )
        db.add(repo)
        await db.flush()
        for f in files:
            f.repo_id = repo.id
            db.add(f)
        await db.commit()
        return repo.id


def test_extract_keywords_drops_stopwords_and_short_words():
    keywords = _extract_keywords("Where is the entry point for auth?")
    assert "entry" in keywords
    assert "point" in keywords
    assert "auth" in keywords
    assert "where" not in keywords
    assert "the" not in keywords
    assert "is" not in keywords


def test_extract_keywords_returns_empty_for_pure_filler():
    assert _extract_keywords("hi there") == []


@pytest.mark.asyncio
async def test_returns_none_for_a_question_with_no_extractable_keywords(db_session):
    result = await build_deterministic_answer(db_session, uuid.uuid4(), "hi")
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_repo_has_no_files(db_session):
    result = await build_deterministic_answer(db_session, uuid.uuid4(), "explain the authentication flow")
    assert result is None


@pytest.mark.asyncio
async def test_matches_by_file_path_when_available():
    repo_id = await _create_repo_with_files([
        File(path="app/auth/login.py", content="def login(): pass"),
        File(path="app/db/models.py", content="class User: pass"),
    ])
    async with async_session_maker() as db:
        result = await build_deterministic_answer(db, repo_id, "how does auth work?")

    assert result is not None
    assert "app/auth/login.py" in result
    assert "app/db/models.py" not in result


@pytest.mark.asyncio
async def test_falls_back_to_content_scan_when_no_path_matches():
    repo_id = await _create_repo_with_files([
        File(path="main.py", content="def handle_webhook_payload(): pass"),
        File(path="utils.py", content="def add(a, b): return a + b"),
    ])
    async with async_session_maker() as db:
        result = await build_deterministic_answer(db, repo_id, "where is the webhook payload handled?")

    assert result is not None
    assert "main.py" in result
    assert "utils.py" not in result


@pytest.mark.asyncio
async def test_returns_none_when_nothing_matches_at_all():
    repo_id = await _create_repo_with_files([File(path="main.py", content="def main(): pass")])
    async with async_session_maker() as db:
        result = await build_deterministic_answer(db, repo_id, "explain the graphql subscription resolver")

    assert result is None


@pytest.mark.asyncio
async def test_includes_a_real_code_snippet_from_the_matched_file():
    # Genuinely RAG-like, not just a file list: the reply must include the
    # actual line the keyword appears on, with line numbers, from the real
    # file content -- not a placeholder.
    content = "\n".join([
        "import os",
        "",
        "def handle_webhook_payload(request):",
        "    return process(request.body)",
        "",
    ])
    repo_id = await _create_repo_with_files([File(path="handlers.py", content=content)])
    async with async_session_maker() as db:
        result = await build_deterministic_answer(db, repo_id, "where is the webhook payload handled?")

    assert result is not None
    assert "Relevant excerpt" in result
    assert "def handle_webhook_payload(request):" in result
    # Line-numbered, matching the real file's line number for that line.
    assert "   3 |" in result
