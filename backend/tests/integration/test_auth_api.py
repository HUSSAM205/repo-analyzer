import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_register_login_and_me_flow():
    email = f"user-{uuid.uuid4()}@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        register_resp = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "supersecret123"}
        )
        assert register_resp.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "supersecret123"}
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == email


@pytest.mark.asyncio
async def test_login_with_wrong_password_rejected():
    email = f"user-{uuid.uuid4()}@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
        resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_api_key_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/api-keys", json={"name": "ci-key"})
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_guest_endpoint_creates_usable_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        guest_resp = await client.post("/api/v1/auth/guest")
        assert guest_resp.status_code == 201
        body = guest_resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

        me_resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me_resp.status_code == 200
        me_body = me_resp.json()
        assert me_body["is_guest"] is True
        assert me_body["email"] is None


@pytest.mark.asyncio
async def test_guest_token_can_call_existing_authenticated_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        guest_resp = await client.post("/api/v1/auth/guest")
        headers = {"Authorization": f"Bearer {guest_resp.json()['access_token']}"}

        list_resp = await client.get("/api/v1/repos", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json() == []


@pytest.mark.asyncio
async def test_each_guest_call_creates_a_distinct_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/auth/guest")
        second = await client.post("/api/v1/auth/guest")

        first_me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"}
        )
        second_me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"}
        )
        assert first_me.json()["id"] != second_me.json()["id"]
