"""Pydantic v2 schemas for Feedback and UnansweredQuestion."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import FeedbackRating, UnansweredStatus


class FeedbackCreate(BaseModel):
    """Schema for creating feedback on a message."""

    message_id: uuid.UUID
    rating: FeedbackRating
    reason: str | None = Field(default=None, max_length=255)
    comment: str | None = None


class FeedbackResponse(BaseModel):
    """Feedback response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    rating: FeedbackRating
    reason: str | None
    comment: str | None
    chunk_ids: list
    created_at: datetime


class UnansweredQuestionCreate(BaseModel):
    """Schema for creating an unanswered question entry."""

    question: str = Field(..., min_length=1)
    language: str = Field(default="fr", pattern=r"^(fr|ar|en)$")
    source_conversation_id: uuid.UUID | None = None


class UnansweredQuestionUpdate(BaseModel):
    """Schema for updating an unanswered question. All fields optional."""

    proposed_answer: str | None = None
    status: UnansweredStatus | None = None
    review_note: str | None = None

    @model_validator(mode="after")
    def validate_approval_requires_answer(self) -> UnansweredQuestionUpdate:
        """If approving or modifying, proposed_answer must be provided."""
        requires_answer = {UnansweredStatus.approved, UnansweredStatus.modified}
        if self.status in requires_answer and not self.proposed_answer:
            msg = f"proposed_answer is required when status is '{self.status.value}'"
            raise ValueError(msg)
        return self


class UnansweredQuestionResponse(BaseModel):
    """Unanswered question response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    language: str
    frequency: int
    proposed_answer: str | None
    status: UnansweredStatus
    reviewed_by: uuid.UUID | None
    review_note: str | None
    source_conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class UnansweredQuestionList(BaseModel):
    """Paginated list of unanswered questions."""

    items: list[UnansweredQuestionResponse]
    total: int
    page: int
    page_size: int


class FeedbackList(BaseModel):
    """Paginated list of feedback entries."""

    items: list[FeedbackResponse]
    total: int
    page: int
    page_size: int
