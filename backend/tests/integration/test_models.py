import uuid

import pytest
from sqlalchemy import select

from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_and_query_user(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.id == user.id))
    fetched = result.scalar_one()
    assert fetched.email == user.email


@pytest.mark.asyncio
async def test_code_chunk_vector_similarity_search(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    close_vector = [0.1] * 768
    far_vector = [0.9] * 768

    chunk_close = CodeChunk(
        repo_id=repo.id, file_path="a.py", symbol_name="foo", node_type=NodeType.FUNCTION,
        start_line=1, end_line=5, content="def foo(): pass", embedding=close_vector,
    )
    chunk_far = CodeChunk(
        repo_id=repo.id, file_path="b.py", symbol_name="bar", node_type=NodeType.FUNCTION,
        start_line=1, end_line=5, content="def bar(): pass", embedding=far_vector,
    )
    db_session.add_all([chunk_close, chunk_far])
    await db_session.flush()

    query_vector = [0.1] * 768
    result = await db_session.execute(
        select(CodeChunk).order_by(CodeChunk.embedding.cosine_distance(query_vector)).limit(1)
    )
    nearest = result.scalar_one()
    assert nearest.id == chunk_close.id
