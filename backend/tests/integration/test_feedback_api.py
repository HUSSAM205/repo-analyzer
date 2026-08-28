import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"feedback-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_submit_feedback_returns_202_even_when_email_is_unconfigured(monkeypatch):
    # No RESEND_API_KEY/FEEDBACK_RECIPIENT_EMAIL in the test environment --
    # the submission must still succeed from the user's point of view (see
    # feedback_email.py's docstring for why).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/feedback",
            json={"type": "bug", "message": "the compare modal flickers on close"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202, resp.text
        assert resp.json() == {"sent": False}


@pytest.mark.asyncio
async def test_submit_feedback_sends_email_when_configured(monkeypatch):
    from app.api.routes import feedback as feedback_module

    async def fake_send(**kwargs):
        fake_send.called_with = kwargs
        return True

    monkeypatch.setattr(feedback_module, "send_feedback_email", fake_send)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/feedback",
            json={"type": "rating", "message": "love it", "rating": 5, "contact_email": "a@b.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        assert resp.json() == {"sent": True}
        assert fake_send.called_with["feedback_type"] == "rating"
        assert fake_send.called_with["rating"] == 5
        assert fake_send.called_with["contact_email"] == "a@b.com"


@pytest.mark.asyncio
async def test_submit_feedback_rejects_empty_message():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/feedback",
            json={"type": "bug", "message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_feedback_allows_an_empty_message_for_a_rating_submission():
    # A rating conveys real feedback via its stars alone -- the message is
    # optional in that one case, unlike bug/feature submissions.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/feedback",
            json={"type": "rating", "message": "", "rating": 4},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202, resp.text


@pytest.mark.asyncio
async def test_submit_feedback_rejects_an_out_of_range_rating():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/feedback",
            json={"type": "rating", "message": "x", "rating": 6},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_feedback_requires_authentication():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/feedback", json={"type": "bug", "message": "x"})
        assert resp.status_code == 403
