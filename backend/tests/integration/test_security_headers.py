import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_security_headers_present_on_a_successful_response():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert "max-age=63072000" in resp.headers["strict-transport-security"]
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "no-referrer"
        assert resp.headers["cross-origin-opener-policy"] == "same-origin"


@pytest.mark.asyncio
async def test_security_headers_present_even_on_an_error_response():
    # A 404 (or any error) must not skip the security headers -- they're
    # applied by wrapping the whole ASGI call chain, not attached per-route.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/repos/00000000-0000-0000-0000-000000000000")

        assert resp.status_code in (401, 403, 404)
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
