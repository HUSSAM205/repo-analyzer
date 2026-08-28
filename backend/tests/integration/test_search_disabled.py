import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_search_returns_503_without_ever_calling_embed_text_when_disabled(monkeypatch):
    # Regression coverage for the one path into embedding that
    # chat.py's own tool-exclusion doesn't cover: calling this route
    # directly must not attempt to load the ~500MB CodeBERT model on a
    # deployment that disabled embedding specifically because that model
    # doesn't fit its memory budget.
    from app.api.routes import search as search_module

    monkeypatch.setattr(search_module.settings, "enable_embedding", False)

    def _exploding_embed_text(text):
        raise AssertionError("embed_text must never be called when embedding is disabled")

    monkeypatch.setattr(search_module, "embed_text", _exploding_embed_text)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"search-disabled-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
        login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)

        async with async_session_maker() as db:
            repo = Repo(
                user_id=me_resp.json()["id"], url=f"https://github.com/example/search-disabled-{uuid.uuid4()}",
                name="repo", status=RepoStatus.READY,
            )
            db.add(repo)
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.post(
            "/api/v1/search", json={"repo_id": repo_id, "query": "anything"}, headers=headers
        )
        assert resp.status_code == 503
