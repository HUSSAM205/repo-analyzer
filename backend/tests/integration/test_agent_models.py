import uuid

import pytest
from sqlalchemy import select

from app.db.models import Conversation, File, Message, MessageRole, Repo, RepoStatus, User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_and_query_file(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    file = File(repo_id=repo.id, path="src/main.py", content="def main(): pass")
    db_session.add(file)
    await db_session.flush()

    result = await db_session.execute(select(File).where(File.repo_id == repo.id))
    fetched = result.scalar_one()
    assert fetched.path == "src/main.py"
    assert fetched.content == "def main(): pass"


@pytest.mark.asyncio
async def test_conversation_and_messages_roundtrip(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo2", name="repo2", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    conversation = Conversation(repo_id=repo.id, user_id=user.id, title="First chat")
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(Message(conversation_id=conversation.id, role=MessageRole.USER, content="What does main do?"))
    db_session.add(Message(conversation_id=conversation.id, role=MessageRole.ASSISTANT, content="It calls pass."))
    await db_session.flush()

    result = await db_session.execute(select(Conversation).where(Conversation.id == conversation.id))
    fetched = result.scalar_one()
    await db_session.refresh(fetched, attribute_names=["messages"])
    assert len(fetched.messages) == 2
    assert fetched.messages[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_files_unique_constraint_per_repo_and_path(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo3", name="repo3", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    db_session.add(File(repo_id=repo.id, path="a.py", content="one"))
    await db_session.flush()
    db_session.add(File(repo_id=repo.id, path="a.py", content="two"))

    with pytest.raises(Exception):
        await db_session.flush()
