"""Pydantic v2 schemas for the Supervised Learning API.

Request schemas for approve/reject/edit operations. Response schemas
are reused from schemas.feedback (UnansweredQuestionResponse, UnansweredQuestionList).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApproveRequest(BaseModel):
    """Approve an unanswered question for Qdrant reinjection.

    If proposed_answer is provided, it overrides the existing AI proposal
    and the question status becomes 'modified'. Otherwise, the existing
    proposed_answer is used and status becomes 'approved'.
    """

    proposed_answer: str | None = None
    review_note: str | None = None


class RejectRequest(BaseModel):
    """Reject an unanswered question — it will not be reinjected."""

    review_note: str | None = None


class EditRequest(BaseModel):
    """Edit the proposed answer without approving.

    Status remains 'pending'. The admin must approve separately.
    """

    proposed_answer: str = Field(..., min_length=1)
    review_note: str | None = None


class LearningStatsResponse(BaseModel):
    """Supervised learning statistics for the dashboard."""

    total: int
    by_status: dict[str, int]
    approval_rate: float
    avg_review_time_hours: float | None
    top_questions: list[dict]
