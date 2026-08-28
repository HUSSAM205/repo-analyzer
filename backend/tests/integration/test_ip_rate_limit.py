import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import settings as rate_limit_settings
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"iprate-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_ip_rate_limit_applies_across_different_user_accounts():
    # The whole point of the IP gate: it must trip even when each request
    # comes from a DIFFERENT (freshly registered) account, since per-user
    # limiting alone can't stop a single source from just registering a new
    # guest/account per request to dodge it.
    same_ip_headers = {"X-Forwarded-For": "203.0.113.42"}
    request_count = rate_limit_settings.rate_limit_ip_analyze_bucket_capacity + 3

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Registering (bcrypt-hashing a password) is comparatively slow --
        # doing it inside the rate-limited loop below would let the token
        # bucket refill between requests almost as fast as it's consumed,
        # defeating the point of the test. All accounts are created upfront,
        # outside the timed section, so the actual rate-limited requests fire
        # back-to-back.
        tokens = [await _register_and_login(client) for _ in range(request_count)]

        last_status = None
        for token in tokens:
            resp = await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": f"https://github.com/octocat/iprate-{uuid.uuid4()}"},
                headers={"Authorization": f"Bearer {token}", **same_ip_headers},
            )
            last_status = resp.status_code

        assert last_status == 429


@pytest.mark.asyncio
async def test_ip_rate_limit_does_not_affect_a_different_ip():
    capacity = rate_limit_settings.rate_limit_ip_analyze_bucket_capacity

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Exhaust the bucket for one IP (accounts created upfront -- see the
        # comment in test_ip_rate_limit_applies_across_different_user_accounts
        # for why that matters here).
        exhausted_ip_headers = {"X-Forwarded-For": "203.0.113.99"}
        tokens = [await _register_and_login(client) for _ in range(capacity + 3)]
        for token in tokens:
            await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": f"https://github.com/octocat/iprate-a-{uuid.uuid4()}"},
                headers={"Authorization": f"Bearer {token}", **exhausted_ip_headers},
            )

        # A request from a distinct IP must be unaffected.
        fresh_ip_headers = {"X-Forwarded-For": "198.51.100.7"}
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": f"https://github.com/octocat/iprate-b-{uuid.uuid4()}"},
            headers={"Authorization": f"Bearer {token}", **fresh_ip_headers},
        )
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_takes_only_the_first_hop_of_x_forwarded_for():
    # X-Forwarded-For is proxy-appended left-to-right with the real client's
    # IP first -- a multi-hop value (e.g. through Render's own edge plus any
    # other intermediary) must key on that first address, not the whole
    # header or the last hop.
    from app.core.rate_limit import _client_ip
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.1, 10.0.0.5, 10.0.0.6")],
        "client": ("10.0.0.6", 12345),
    }
    request = Request(scope)
    assert _client_ip(request) == "203.0.113.1"
