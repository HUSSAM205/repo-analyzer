from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.core.feedback_email import send_feedback_email
from app.db.models import User
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(
    payload: FeedbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> FeedbackResponse:
    sent = await send_feedback_email(
        feedback_type=payload.type,
        message=payload.message,
        rating=payload.rating,
        contact_email=payload.contact_email,
        user_id=str(current_user.id),
    )
    # Always 202 regardless of email outcome -- see feedback_email.py's
    # own docstring for why a misconfigured/down provider must never
    # surface as a failed request here.
    return FeedbackResponse(sent=sent)
