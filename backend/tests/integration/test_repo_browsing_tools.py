import uuid

import pytest

from app.core.agent_tools import list_directory, read_file
from app.core.token_budget import MAX_CONTEXT_CHARS
from app.db.models import File, Repo, RepoStatus, User

# Unlike search_code (tests/integration/test_agent_tools.py), these tools are
# pure DB lookups with no embedding model involved -- kept out of the `slow`
# suite so they run with the fast integration tests.
pytestmark = pytest.mark.integration


async def _make_repo(db_session) -> Repo:
    user = User(email=f"browse-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(
        user_id=user.id, url=f"https://github.com/example/browserepo-{uuid.uuid4()}",
        name="browserepo", status=RepoStatus.READY,
    )
    db_session.add(repo)
    await db_session.flush()
    return repo


async def _add_files(db_session, repo_id, paths: list[str]) -> None:
    for path in paths:
        db_session.add(File(repo_id=repo_id, path=path, content=f"content of {path}"))
    await db_session.flush()


@pytest.mark.asyncio
async def test_list_directory_lists_root_files_and_directories(db_session):
    repo = await _make_repo(db_session)
    await _add_files(db_session, repo.id, ["README.md", "package.json", "src/index.js", "src/utils/helpers.js"])

    result = await list_directory(db_session, repo.id, "")

    lines = result.split("\n")
    assert "README.md" in lines
    assert "package.json" in lines
    assert "src/" in lines
    # A file nested two levels deep must not leak into the root listing --
    # only its top-level directory ("src/") should appear.
    assert "src/index.js" not in lines
    assert "src/utils/" not in lines


@pytest.mark.asyncio
async def test_list_directory_lists_a_subdirectory_non_recursively(db_session):
    repo = await _make_repo(db_session)
    await _add_files(db_session, repo.id, ["src/index.js", "src/utils/helpers.js", "src/utils/format.js"])

    result = await list_directory(db_session, repo.id, "src")

    lines = result.split("\n")
    assert "index.js" in lines
    assert "utils/" in lines
    # utils/ is shown as a directory entry, not expanded into its own files.
    assert "helpers.js" not in lines
    assert "format.js" not in lines


@pytest.mark.asyncio
async def test_list_directory_handles_leading_and_trailing_slashes(db_session):
    repo = await _make_repo(db_session)
    await _add_files(db_session, repo.id, ["src/index.js"])

    assert await list_directory(db_session, repo.id, "/src/") == await list_directory(db_session, repo.id, "src")


@pytest.mark.asyncio
async def test_list_directory_reports_a_clear_message_for_a_nonexistent_directory(db_session):
    repo = await _make_repo(db_session)
    await _add_files(db_session, repo.id, ["README.md"])

    result = await list_directory(db_session, repo.id, "does/not/exist")

    assert "No such directory" in result
    assert "does/not/exist" in result


@pytest.mark.asyncio
async def test_list_directory_reports_empty_for_a_repo_with_no_files(db_session):
    repo = await _make_repo(db_session)

    result = await list_directory(db_session, repo.id, "")

    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_read_file_returns_full_content_with_path_header(db_session):
    repo = await _make_repo(db_session)
    db_session.add(File(repo_id=repo.id, path="src/main.py", content="def main():\n    pass\n"))
    await db_session.flush()

    result = await read_file(db_session, repo.id, "src/main.py")

    assert "src/main.py" in result
    assert "def main():" in result
    assert "pass" in result


@pytest.mark.asyncio
async def test_read_file_reports_a_clear_message_for_a_nonexistent_file(db_session):
    repo = await _make_repo(db_session)

    result = await read_file(db_session, repo.id, "does/not/exist.py")

    assert "No such file" in result
    assert "does/not/exist.py" in result


@pytest.mark.asyncio
async def test_read_file_truncates_content_over_the_token_budget(db_session):
    repo = await _make_repo(db_session)
    huge_content = "x" * (MAX_CONTEXT_CHARS + 5_000)
    db_session.add(File(repo_id=repo.id, path="huge.txt", content=huge_content))
    await db_session.flush()

    result = await read_file(db_session, repo.id, "huge.txt")

    assert len(result) < len(huge_content)
    assert "truncated" in result
    assert "context budget" in result


@pytest.mark.asyncio
async def test_read_file_is_scoped_to_the_requesting_repo(db_session):
    repo_a = await _make_repo(db_session)
    repo_b = await _make_repo(db_session)
    db_session.add(File(repo_id=repo_b.id, path="secret.py", content="secret content"))
    await db_session.flush()

    result = await read_file(db_session, repo_a.id, "secret.py")

    assert "No such file" in result
    assert "secret content" not in result
