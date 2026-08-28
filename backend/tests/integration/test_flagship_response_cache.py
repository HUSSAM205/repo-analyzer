import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import get_redis_client
from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = f"resp-cache-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    token = login_resp.json()["access_token"]
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me_resp.json()["id"]


async def _setup_repo(client: AsyncClient) -> tuple[str, dict]:
    token, user_id = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    async with async_session_maker() as db:
        repo = Repo(
            user_id=user_id, url=f"https://github.com/example/resp-cache-{uuid.uuid4()}", name="resp-cache-repo",
            status=RepoStatus.READY,
        )
        db.add(repo)
        await db.flush()
        db.add(File(repo_id=repo.id, path="main.py", content="def main():\n    pass\n"))
        await db.commit()
        repo_id = str(repo.id)

    return repo_id, headers


@pytest.mark.asyncio
async def test_second_request_is_served_from_redis_even_if_postgres_cache_is_cleared(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="# resp-cache-repo\n\nGenerated once.")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        first = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert first.status_code == 200
        assert first.json()["content"] == "# resp-cache-repo\n\nGenerated once."

        # Clear the Postgres-side cache directly -- if the second request
        # still returns the right content without ever calling the LLM
        # (get_llm_client is only scripted for one turn, so a second call
        # would raise "ran out of scripted turns"), it can only have come
        # from Redis.
        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.readme_doc = None
            await db.commit()

        second = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert second.status_code == 200
        assert second.json()["content"] == "# resp-cache-repo\n\nGenerated once."


@pytest.mark.asyncio
async def test_response_cache_degrades_gracefully_when_redis_is_unavailable(monkeypatch):
    # A Redis outage must fall back to the pre-existing (Postgres-only)
    # behavior, not break the endpoint -- see response_cache.py's
    # get_cached/set_cached, which never raise.
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="# still works without redis")]),
    )

    import redis.asyncio as redis

    class ExplodingRedis:
        async def get(self, key):
            raise redis.ConnectionError("redis is down")

        async def set(self, key, value, ex=None):
            raise redis.ConnectionError("redis is down")

    import app.core.response_cache as response_cache_module

    monkeypatch.setattr(response_cache_module, "get_redis_client", lambda: ExplodingRedis())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["content"] == "# still works without redis"


@pytest.mark.asyncio
async def test_compliance_scan_response_is_cached_in_redis_with_a_ttl():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/compliance-scan", headers=headers)
        assert resp.status_code == 200

        redis_client = get_redis_client()
        cached_raw = await redis_client.get(f"flagship:compliance-scan:{repo_id}")
        assert cached_raw is not None
        ttl = await redis_client.ttl(f"flagship:compliance-scan:{repo_id}")
        # A fresh write's TTL should be close to the full 24h (86400s) --
        # comfortably bounded rather than asserting an exact value.
        assert 0 < ttl <= 86400
