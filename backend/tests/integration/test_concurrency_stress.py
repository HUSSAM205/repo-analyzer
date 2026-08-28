"""Concurrency/scalability regression coverage.

Not a substitute for a real external load-testing tool (k6/locust) against
a deployed instance -- pytest-asyncio's event loop and this process's DB
connection pool are shared with every other test, so this is scoped to
what's actually meaningful to assert in-process: many simultaneous requests
against the same hot resource must all succeed, must not deadlock, and must
not corrupt shared state (the Redis response cache, the Postgres
permanent cache, the Redis rate-limit token bucket) under real concurrency
-- not just sequentially, one at a time, like every other test in this
suite exercises.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration

# Comfortably under the DB engine's pool_size=20 + max_overflow=10 (see
# db/session.py) so this exercises real concurrency without the later
# requests simply queueing for a free connection, which would make this a
# test of the connection pool's queue rather than of this endpoint's own
# concurrency safety.
_CONCURRENT_REQUESTS = 25


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = f"stress-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    token = login_resp.json()["access_token"]
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me_resp.json()["id"]


@pytest.mark.asyncio
async def test_many_concurrent_requests_for_the_same_hot_repo_all_succeed():
    # Simulates the actual "1000+ concurrent users" scenario this cache
    # exists for: many people loading the same popular/trending analyzed
    # repo at once. A naive implementation with a race in the cache-aside
    # logic could 500, deadlock, or serve corrupted data under this exact
    # pattern -- sequential tests would never catch that.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        async with async_session_maker() as db:
            repo = Repo(
                user_id=user_id, url=f"https://github.com/example/stress-{uuid.uuid4()}", name="stress-repo",
                status=RepoStatus.READY,
            )
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="main.py", content="def main():\n    pass\n"))
            await db.commit()
            repo_id = str(repo.id)

        async def _fetch():
            return await client.get(f"/api/v1/repos/{repo_id}/compliance-scan", headers=headers)

        responses = await asyncio.gather(*(_fetch() for _ in range(_CONCURRENT_REQUESTS)))

        assert all(r.status_code == 200 for r in responses)
        bodies = [r.json() for r in responses]
        # Every concurrent caller must see the exact same result, whether it
        # raced to compute-and-cache it or hit an already-warm cache.
        assert all(b == bodies[0] for b in bodies)


@pytest.mark.asyncio
async def test_concurrent_requests_from_many_distinct_users_do_not_interfere():
    # A second concurrency shape: many different accounts hitting the
    # rate-limited chat-adjacent analyze endpoint at once, each for their
    # own distinct repo -- must not cross-contaminate each other's
    # rate-limit bucket, DB rows, or response.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        accounts = [await _register_and_login(client) for _ in range(_CONCURRENT_REQUESTS)]

        async def _analyze(token: str):
            return await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": f"https://github.com/octocat/concurrent-{uuid.uuid4()}"},
                headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": f"198.51.100.{hash(token) % 200}"},
            )

        responses = await asyncio.gather(*(_analyze(token) for token, _ in accounts))

        assert all(r.status_code == 202 for r in responses)
        repo_ids = {r.json()["repo_id"] for r in responses}
        # Every distinct submission got its own distinct repo -- none of the
        # concurrent requests accidentally converged onto another's row.
        assert len(repo_ids) == _CONCURRENT_REQUESTS
