"""Supervised Learning API — manage unanswered questions workflow.

Provides endpoints for the back-office to list, generate AI proposals,
approve/reject/edit questions, and view learning statistics.
Approved questions are automatically enqueued for Qdrant reinjection.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.arq import get_arq_pool
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole, UnansweredStatus
from app.models.feedback import UnansweredQuestion
from app.schemas.auth import AdminTokenPayload
from app.schemas.feedback import (
    UnansweredQuestionList,
    UnansweredQuestionResponse,
)
from app.schemas.learning import (
    ApproveRequest,
    EditRequest,
    LearningStatsResponse,
    RejectRequest,
)
from app.services.learning.service import get_learning_service

logger = structlog.get_logger()

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/questions", response_model=UnansweredQuestionList)
async def list_questions(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        ),
    ),
    status: UnansweredStatus | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UnansweredQuestionList:
    """List unanswered questions with optional filters and pagination.

    Sorted by frequency DESC (most asked first), then created_at DESC.
    """
    svc = get_learning_service()
    items, total = await svc.get_unanswered_questions(
        tenant,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return UnansweredQuestionList(
        items=[UnansweredQuestionResponse.model_validate(q) for q in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/questions/{question_id}",
    response_model=UnansweredQuestionResponse,
)
async def get_question(
    question_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        ),
    ),
) -> UnansweredQuestionResponse:
    """Get a single unanswered question by ID.

    Returns 404 if not found.
    """
    from app.core.exceptions import ResourceNotFoundError

    async with tenant.db_session() as session:
        result = await session.execute(
            select(UnansweredQuestion).where(
                UnansweredQuestion.id == question_id,
            ),
        )
        question = result.scalar_one_or_none()

    if question is None:
        raise ResourceNotFoundError(
            f"UnansweredQuestion {question_id} not found",
        )

    return UnansweredQuestionResponse.model_validate(question)


@router.post(
    "/questions/{question_id}/generate",
    response_model=UnansweredQuestionResponse,
)
async def generate_proposal(
    question_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        ),
    ),
) -> UnansweredQuestionResponse:
    """Generate an AI-proposed answer via Gemini.

    Uses the RAG pipeline to search the KB, then Gemini to formulate
    a proposed answer. The question must be in 'pending' status.
    """
    svc = get_learning_service()
    question = await svc.generate_ai_proposal(tenant, question_id)
    return UnansweredQuestionResponse.model_validate(question)


@router.post(
    "/questions/{question_id}/approve",
    response_model=UnansweredQuestionResponse,
)
async def approve_question(
    question_id: uuid.UUID,
    body: ApproveRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
        ),
    ),
) -> UnansweredQuestionResponse:
    """Approve a question and enqueue Qdrant reinjection.

    If proposed_answer is provided in the body, it overrides the existing
    AI proposal (status becomes 'modified'). Otherwise, the existing
    proposed_answer is used (status becomes 'approved').

    Automatically enqueues the reinject_learning_task worker.
    """
    svc = get_learning_service()
    admin_id = uuid.UUID(admin.sub)

    question = await svc.approve_question(
        tenant,
        question_id,
        admin_id,
        proposed_answer=body.proposed_answer,
    )

    # Enqueue Qdrant reinjection (best-effort)
    try:
        pool = get_arq_pool()
        await pool.enqueue_job(
            "reinject_learning_task",
            tenant.slug,
            str(question_id),
        )
    except Exception:
        logger.warning(
            "reinject_enqueue_failed",
            question_id=str(question_id),
            tenant=tenant.slug,
            exc_info=True,
        )

    return UnansweredQuestionResponse.model_validate(question)


@router.post(
    "/questions/{question_id}/reject",
    response_model=UnansweredQuestionResponse,
)
async def reject_question(
    question_id: uuid.UUID,
    body: RejectRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
        ),
    ),
) -> UnansweredQuestionResponse:
    """Reject a question — it will not be reinjected into Qdrant."""
    svc = get_learning_service()
    admin_id = uuid.UUID(admin.sub)

    question = await svc.reject_question(
        tenant,
        question_id,
        admin_id,
        review_note=body.review_note,
    )
    return UnansweredQuestionResponse.model_validate(question)


@router.post(
    "/questions/{question_id}/edit",
    response_model=UnansweredQuestionResponse,
)
async def edit_proposal(
    question_id: uuid.UUID,
    body: EditRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        ),
    ),
) -> UnansweredQuestionResponse:
    """Edit the proposed answer and mark as modified (approved).

    The edited answer replaces any AI-generated proposal. Status becomes
    'modified', indicating human editing occurred. The question is ready
    for Qdrant reinjection via the approve endpoint.
    """
    svc = get_learning_service()
    admin_id = uuid.UUID(admin.sub)

    question = await svc.edit_proposal(
        tenant,
        question_id,
        admin_id,
        proposed_answer=body.proposed_answer,
        review_note=body.review_note,
    )
    return UnansweredQuestionResponse.model_validate(question)


@router.get("/stats", response_model=LearningStatsResponse)
async def get_learning_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        ),
    ),
) -> LearningStatsResponse:
    """Get supervised learning statistics for the dashboard.

    Returns counts by status, approval rate, average review time,
    and top 5 pending questions by frequency.
    """
    svc = get_learning_service()
    stats = await svc.get_learning_stats(tenant)
    return LearningStatsResponse(**stats)
