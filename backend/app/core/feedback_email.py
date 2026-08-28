"""Feedback email dispatch via Resend's HTTP API -- see config.py's
resend_api_key/feedback_recipient_email for why Resend over raw SMTP.

Deliberately never raises: a misconfigured or down email provider is an
operational concern for whoever runs this deployment (visible in server
logs), not something that should turn into a failed request for whoever
just took the time to submit feedback. See feedback.py's route, which
always returns 202 regardless of this function's result.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_REQUEST_TIMEOUT_SECONDS = 10


async def send_feedback_email(
    feedback_type: str,
    message: str,
    rating: int | None,
    contact_email: str | None,
    user_id: str,
) -> bool:
    settings = get_settings()
    if not settings.resend_api_key or not settings.feedback_recipient_email:
        logger.warning(
            "Feedback email not sent -- RESEND_API_KEY or FEEDBACK_RECIPIENT_EMAIL is not "
            "configured. type=%s rating=%s contact_email=%s message=%s",
            feedback_type, rating, contact_email, message,
        )
        return False

    subject = f"[RepoLens AI Feedback] {feedback_type}"
    if rating is not None:
        subject += f" ({rating}/5)"

    text_body = "\n".join([
        f"Type: {feedback_type}",
        f"Rating: {rating if rating is not None else 'n/a'}",
        f"From user: {user_id}",
        f"Contact email: {contact_email or 'not provided'}",
        "",
        "Message:",
        message,
    ])

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.feedback_sender_email,
                    "to": [settings.feedback_recipient_email],
                    "subject": subject,
                    "text": text_body,
                },
            )
    except httpx.HTTPError:
        logger.exception("Feedback email dispatch failed (network error)")
        return False

    if response.status_code >= 400:
        logger.warning("Feedback email dispatch failed: %s %s", response.status_code, response.text)
        return False

    return True
