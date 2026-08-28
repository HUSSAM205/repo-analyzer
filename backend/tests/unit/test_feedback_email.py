import httpx
import pytest

from app.config import get_settings
from app.core.feedback_email import send_feedback_email


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, response=None, raise_error: Exception | None = None):
        self._response = response
        self._raise_error = raise_error
        self.last_call: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.last_call = {"url": url, "headers": headers, "json": json}
        if self._raise_error:
            raise self._raise_error
        return self._response


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_returns_false_and_does_not_call_resend_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("FEEDBACK_RECIPIENT_EMAIL", raising=False)

    sent = await send_feedback_email("bug", "it's broken", None, None, "user-1")

    assert sent is False


async def test_sends_via_resend_when_configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("FEEDBACK_RECIPIENT_EMAIL", "admin@example.com")

    fake_client = _FakeAsyncClient(response=_FakeResponse(200))
    monkeypatch.setattr("app.core.feedback_email.httpx.AsyncClient", lambda **kwargs: fake_client)

    sent = await send_feedback_email("feature", "please add dark mode toggle", None, "user@example.com", "user-1")

    assert sent is True
    assert fake_client.last_call["headers"]["Authorization"] == "Bearer re_test_key"
    assert fake_client.last_call["json"]["to"] == ["admin@example.com"]
    assert "please add dark mode toggle" in fake_client.last_call["json"]["text"]


async def test_includes_rating_in_subject_and_body_when_present(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("FEEDBACK_RECIPIENT_EMAIL", "admin@example.com")

    fake_client = _FakeAsyncClient(response=_FakeResponse(200))
    monkeypatch.setattr("app.core.feedback_email.httpx.AsyncClient", lambda **kwargs: fake_client)

    await send_feedback_email("rating", "great tool", 5, None, "user-1")

    assert "(5/5)" in fake_client.last_call["json"]["subject"]
    assert "Rating: 5" in fake_client.last_call["json"]["text"]


async def test_returns_false_on_resend_error_response(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("FEEDBACK_RECIPIENT_EMAIL", "admin@example.com")

    fake_client = _FakeAsyncClient(response=_FakeResponse(401, "invalid API key"))
    monkeypatch.setattr("app.core.feedback_email.httpx.AsyncClient", lambda **kwargs: fake_client)

    sent = await send_feedback_email("bug", "x", None, None, "user-1")

    assert sent is False


async def test_returns_false_and_does_not_raise_on_network_error(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("FEEDBACK_RECIPIENT_EMAIL", "admin@example.com")

    fake_client = _FakeAsyncClient(raise_error=httpx.ConnectError("connection refused"))
    monkeypatch.setattr("app.core.feedback_email.httpx.AsyncClient", lambda **kwargs: fake_client)

    sent = await send_feedback_email("bug", "x", None, None, "user-1")

    assert sent is False
