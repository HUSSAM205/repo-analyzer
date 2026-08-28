import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_keepalive_touches_the_database_and_reports_roundtrip_time():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/keepalive")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["database_roundtrip_ms"], (int, float))
    assert body["database_roundtrip_ms"] >= 0


@pytest.mark.asyncio
async def test_keepalive_requires_no_authentication():
    # Meant to be hit by an external uptime pinger with no credentials --
    # see main.py's comment on why this exists.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/keepalive")

    assert resp.status_code != 401
    assert resp.status_code != 403
