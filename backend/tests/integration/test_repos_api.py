import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"repos-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_analyze_endpoint_creates_job_and_returns_202():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": "https://github.com/octocat/Hello-World"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "repo_id" in body
        assert "job_id" in body

        job_resp = await client.get(f"/api/v1/jobs/{body['job_id']}", headers={"Authorization": f"Bearer {token}"})
        assert job_resp.status_code == 200
        assert job_resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_analyze_endpoint_rate_limited_after_capacity():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        last_status = None
        for _ in range(10):
            resp = await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": "https://github.com/octocat/Hello-World"},
                headers=headers,
            )
            last_status = resp.status_code
        assert last_status == 429


@pytest.mark.asyncio
async def test_get_nonexistent_job_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
