from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FeedbackRequest(BaseModel):
    type: Literal["bug", "feature", "rating"]
    # Not min_length=1 at the field level -- a "rating" submission conveys
    # real feedback via its star rating alone, so the message is optional
    # in that one case (enforced below) while still required for bug/
    # feature submissions, which are meaningless without one.
    message: str = Field(default="", max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)
    contact_email: str | None = None

    @model_validator(mode="after")
    def _require_message_unless_rating(self) -> "FeedbackRequest":
        if self.type != "rating" and not self.message.strip():
            raise ValueError("message is required for bug reports and feature requests")
        return self


class FeedbackResponse(BaseModel):
    sent: bool
