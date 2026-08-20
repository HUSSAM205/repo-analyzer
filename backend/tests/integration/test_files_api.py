import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.code_annotation import MAX_ANNOTATION_CONTENT_LENGTH
from app.core.llm import FakeLLMClient, ScriptedTurn
from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration

VALID_ANNOTATIONS_JSON = json.dumps(
    [
        {
            "category": "imports",
            "start_line": 1,
            "end_line": 1,
            "logic_summary": "Imports the module needed below.",
            "flow": "No inputs; makes downstream symbols available.",
            "tips": "None apparent",
        }
    ]
)


async def _register_and_login(client: AsyncClient) -> str:
    email = f"files-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_file_tree_and_content_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=user_id, url=f"https://github.com/example/filesrepo-{uuid.uuid4()}", name="filesrepo", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="src/main.py", content="def main(): pass"))
            db.add(File(repo_id=repo.id, path="src/utils/helpers.py", content="def helper(): pass"))
            db.add(File(repo_id=repo.id, path="README.md", content="# Hello"))
            await db.commit()
            repo_id = str(repo.id)

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=headers)
        assert tree_resp.status_code == 200
        entries = tree_resp.json()["entries"]
        names_at_root = {e["name"] for e in entries}
        assert names_at_root == {"src", "README.md"}
        src_entry = next(e for e in entries if e["name"] == "src")
        assert src_entry["type"] == "directory"
        assert {c["name"] for c in src_entry["children"]} == {"main.py", "utils"}

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "src/main.py"}, headers=headers
        )
        assert content_resp.status_code == 200
        assert content_resp.json()["content"] == "def main(): pass"

        missing_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "nope.py"}, headers=headers
        )
        assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_files_endpoints_accessible_by_other_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        owner_me = await client.get("/api/v1/auth/me", headers=owner_headers)
        owner_id = owner_me.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=owner_id, url=f"https://github.com/example/privatefiles-{uuid.uuid4()}", name="privatefiles", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="anything.py", content="print('hi')"))
            await db.commit()
            repo_id = str(repo.id)

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=other_headers)
        assert tree_resp.status_code == 200

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "anything.py"}, headers=other_headers
        )
        assert content_resp.status_code == 200
        assert content_resp.json()["content"] == "print('hi')"


async def _setup_repo_with_file(client: AsyncClient, content: str = "import os\n") -> tuple[str, dict, str]:
    token = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me_resp.json()["id"]

    path = "src/annotated.py"
    async with async_session_maker() as db:
        repo = Repo(
            user_id=user_id,
            url=f"https://github.com/example/annotrepo-{uuid.uuid4()}",
            name="annotrepo",
            status=RepoStatus.READY,
        )
        db.add(repo)
        await db.flush()
        db.add(File(repo_id=repo.id, path=path, content=content))
        await db.commit()
        repo_id = str(repo.id)

    return repo_id, headers, path


@pytest.mark.asyncio
async def test_file_annotations_cache_hit_skips_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called on a cache hit")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("app.api.routes.files.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers, path = await _setup_repo_with_file(client)

        cached_blocks = [
            {
                "category": "imports",
                "start_line": 1,
                "end_line": 1,
                "logic_summary": "Cached summary.",
                "flow": "Cached flow.",
                "tips": "None apparent",
            }
        ]
        async with async_session_maker() as db:
            result = await db.execute(select(File).where(File.repo_id == uuid.UUID(repo_id), File.path == path))
            file = result.scalar_one()
            file.annotations = cached_blocks
            await db.commit()

        resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/annotations", params={"path": path}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == path
        assert body["blocks"] == cached_blocks


@pytest.mark.asyncio
async def test_file_annotations_cache_miss_success_populates_db(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.files.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_ANNOTATIONS_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers, path = await _setup_repo_with_file(client)

        resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/annotations", params={"path": path}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == path
        assert len(body["blocks"]) == 1
        assert body["blocks"][0]["category"] == "imports"

        async with async_session_maker() as db:
            result = await db.execute(select(File).where(File.repo_id == uuid.UUID(repo_id), File.path == path))
            file = result.scalar_one()
            assert file.annotations is not None
            assert file.annotations[0]["category"] == "imports"


@pytest.mark.asyncio
async def test_file_annotations_cache_miss_failure_returns_503_and_does_not_cache(monkeypatch):
    class RaisingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("app.api.routes.files.get_llm_client", lambda: RaisingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers, path = await _setup_repo_with_file(client)

        resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/annotations", params={"path": path}, headers=headers
        )
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()

        async with async_session_maker() as db:
            result = await db.execute(select(File).where(File.repo_id == uuid.UUID(repo_id), File.path == path))
            file = result.scalar_one()
            assert file.annotations is None


@pytest.mark.asyncio
async def test_file_annotations_file_not_found_returns_404(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.files.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_ANNOTATIONS_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers, _path = await _setup_repo_with_file(client)

        resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/annotations", params={"path": "nope.py"}, headers=headers
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_file_annotations_oversized_file_returns_413(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called for an oversized file")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("app.api.routes.files.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        oversized_content = "x" * (MAX_ANNOTATION_CONTENT_LENGTH + 1)
        repo_id, headers, path = await _setup_repo_with_file(client, content=oversized_content)

        resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/annotations", params={"path": path}, headers=headers
        )
        assert resp.status_code == 413
