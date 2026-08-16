import uuid

import pytest

from app.core.agent_tools import search_code
from app.core.embeddings import embed_text
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_search_code_returns_formatted_results_with_citations(db_session):
    user = User(email=f"tool-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/toolrepo", name="toolrepo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    content = "def calculate_discount(price, rate):\n    return price * (1 - rate)"
    db_session.add(CodeChunk(
        repo_id=repo.id, file_path="pricing.py", symbol_name="calculate_discount", node_type=NodeType.FUNCTION,
        start_line=10, end_line=11, content=content, embedding=embed_text(content),
    ))
    await db_session.flush()

    result_text = await search_code(db_session, repo.id, "how are discounts calculated")

    assert "pricing.py:10-11" in result_text
    assert "calculate_discount" in result_text
    assert "return price * (1 - rate)" in result_text


@pytest.mark.asyncio
async def test_search_code_returns_no_results_message_when_empty(db_session):
    user = User(email=f"tool-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/emptyrepo", name="emptyrepo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    result_text = await search_code(db_session, repo.id, "anything")
    assert "No matching code found" in result_text
