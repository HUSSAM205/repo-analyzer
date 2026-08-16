import uuid

import pytest

from app.core.embeddings import embed_text
from app.core.search import hybrid_search
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_hybrid_search_finds_relevant_chunk_by_keyword(db_session):
    user = User(email=f"search-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    target_content = "def calculate_tax(income, rate):\n    return income * rate"
    other_content = "def render_homepage():\n    return '<html></html>'"

    db_session.add_all([
        CodeChunk(
            repo_id=repo.id, file_path="tax.py", symbol_name="calculate_tax", node_type=NodeType.FUNCTION,
            start_line=1, end_line=2, content=target_content, embedding=embed_text(target_content),
        ),
        CodeChunk(
            repo_id=repo.id, file_path="views.py", symbol_name="render_homepage", node_type=NodeType.FUNCTION,
            start_line=1, end_line=2, content=other_content, embedding=embed_text(other_content),
        ),
    ])
    await db_session.flush()

    results = await hybrid_search(
        db_session, repo.id, query_text="calculate tax",
        query_embedding=embed_text("compute the tax owed"), limit=5,
    )

    assert len(results) > 0
    assert results[0].symbol_name == "calculate_tax"
