"""Feedback API — collect ratings, view stats, manage unanswered questions.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
POST /feedback is called internally from the webhook when a user clicks a feedback button.
Other endpoints require admin authentication for back-office access.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole, FeedbackRating, UnansweredStatus
from app.schemas.auth import AdminTokenPayload
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackList,
    FeedbackResponse,
    UnansweredQuestionList,
    UnansweredQuestionResponse,
    UnansweredQuestionUpdate,
)
from app.services.feedback.service import get_feedback_service

logger = structlog.get_logger()

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=201, response_model=FeedbackResponse)
async def create_feedback(
    data: FeedbackCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant, AdminRole.supervisor),
    ),
) -> FeedbackResponse:
    """Record a feedback entry.

    Called from webhook processing when a user clicks a feedback button,
    or manually from the back-office for testing.
    chunk_ids are auto-populated from the rated Message.
    """
    svc = get_feedback_service()
    feedback = await svc.create_feedback(tenant, data)
    return FeedbackResponse.model_validate(feedback)


@router.get("", response_model=FeedbackList)
async def list_feedback(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    rating: FeedbackRating | None = Query(default=None),
) -> FeedbackList:
    """List feedback entries (paginated, filterable by rating)."""
    svc = get_feedback_service()
    items, total = await svc.list_feedback(
        tenant,
        page=page,
        page_size=page_size,
        rating=rating,
    )
    return FeedbackList(
        items=[FeedbackResponse.model_validate(f) for f in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats")
async def get_feedback_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        ),
    ),
) -> dict:
    """Get feedback statistics for the back-office dashboard."""
    svc = get_feedback_service()
    return await svc.get_feedback_stats(tenant)


@router.get("/unanswered", response_model=UnansweredQuestionList)
async def list_unanswered_questions(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: UnansweredStatus | None = Query(default=None),
) -> UnansweredQuestionList:
    """List unanswered questions for supervised learning review."""
    svc = get_feedback_service()
    items, total = await svc.list_unanswered_questions(
        tenant,
        page=page,
        page_size=page_size,
        status=status,
    )
    return UnansweredQuestionList(
        items=[UnansweredQuestionResponse.model_validate(q) for q in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/unanswered/{question_id}",
    response_model=UnansweredQuestionResponse,
)
async def update_unanswered_question(
    question_id: uuid.UUID,
    data: UnansweredQuestionUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant),
    ),
) -> UnansweredQuestionResponse:
    """Review an unanswered question: approve, reject, or edit the proposed answer."""
    svc = get_feedback_service()
    question = await svc.update_unanswered_question(
        tenant,
        question_id,
        data,
        admin_id=uuid.UUID(admin.sub),
    )
    return UnansweredQuestionResponse.model_validate(question)
