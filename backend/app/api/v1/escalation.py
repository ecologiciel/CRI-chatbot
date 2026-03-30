"""Escalation API — list, assign, respond, close escalations.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Requires supervisor or admin_tenant role for back-office access.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import NoResultFound

from app.core.exceptions import EscalationConflictError, ResourceNotFoundError
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import (
    AdminRole,
    EscalationPriority,
    EscalationStatus,
)
from app.schemas.auth import AdminTokenPayload
from app.schemas.conversation import MessageResponse
from app.schemas.escalation import (
    EscalationList,
    EscalationRead,
    EscalationResolve,
    EscalationRespond,
    EscalationStats,
)
from app.services.escalation import get_escalation_service

logger = structlog.get_logger()

router = APIRouter(prefix="/escalations", tags=["escalations"])

_ESCALATION_ROLES = (AdminRole.supervisor, AdminRole.admin_tenant)


@router.get("", response_model=EscalationList)
async def list_escalations(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: EscalationStatus | None = Query(default=None),
    priority: EscalationPriority | None = Query(default=None),
    assigned_to: uuid.UUID | None = Query(default=None),
) -> EscalationList:
    """List escalations with optional filters (paginated).

    Ordered by priority (high first) then by creation date (oldest first).
    """
    svc = get_escalation_service()
    items, total = await svc.get_escalations(
        tenant,
        status=status,
        priority=priority,
        assigned_to=assigned_to,
        page=page,
        size=page_size,
    )
    return EscalationList(
        items=[EscalationRead.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=EscalationStats)
async def get_escalation_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> EscalationStats:
    """Dashboard statistics: pending, in_progress, avg times, breakdowns."""
    svc = get_escalation_service()
    stats = await svc.get_escalation_stats(tenant)
    return EscalationStats(**stats)


@router.get("/{escalation_id}", response_model=EscalationRead)
async def get_escalation(
    escalation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> EscalationRead:
    """Fetch a single escalation by ID."""
    svc = get_escalation_service()
    escalation = await svc.get_escalation_by_id(escalation_id, tenant)
    if escalation is None:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        )
    return EscalationRead.model_validate(escalation)


@router.post("/{escalation_id}/assign", response_model=EscalationRead)
async def assign_escalation(
    escalation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> EscalationRead:
    """Self-assign an escalation to the currently authenticated admin.

    Returns 404 if not found, 409 if already assigned or resolved.
    """
    svc = get_escalation_service()

    # Pre-check existence and state
    escalation = await svc.get_escalation_by_id(escalation_id, tenant)
    if escalation is None:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        )
    if escalation.status not in (EscalationStatus.pending,):
        raise EscalationConflictError(
            f"Cannot assign escalation in status '{escalation.status.value}'",
            details={
                "escalation_id": str(escalation_id),
                "current_status": escalation.status.value,
            },
        )

    try:
        result = await svc.assign_escalation(
            escalation_id,
            uuid.UUID(admin.sub),
            tenant,
        )
    except NoResultFound as err:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        ) from err

    return EscalationRead.model_validate(result)


@router.post("/{escalation_id}/respond")
async def respond_to_escalation(
    escalation_id: uuid.UUID,
    body: EscalationRespond,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> dict:
    """Send a WhatsApp message to the user via the tenant's number.

    Returns the WhatsApp message ID (wamid).
    """
    svc = get_escalation_service()

    # Verify escalation exists and is in a respondable state
    escalation = await svc.get_escalation_by_id(escalation_id, tenant)
    if escalation is None:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        )
    if escalation.status not in (
        EscalationStatus.assigned,
        EscalationStatus.in_progress,
    ):
        raise EscalationConflictError(
            f"Cannot respond to escalation in status '{escalation.status.value}'",
            details={
                "escalation_id": str(escalation_id),
                "current_status": escalation.status.value,
            },
        )

    try:
        wamid = await svc.respond_via_whatsapp(
            escalation_id,
            body.message,
            uuid.UUID(admin.sub),
            tenant,
        )
    except NoResultFound as err:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        ) from err

    return {"wamid": wamid}


@router.post("/{escalation_id}/close", response_model=EscalationRead)
async def close_escalation(
    escalation_id: uuid.UUID,
    body: EscalationResolve,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> EscalationRead:
    """Close an escalation. The conversation returns to automatic mode.

    Returns 404 if not found, 409 if already resolved/closed.
    """
    svc = get_escalation_service()

    escalation = await svc.get_escalation_by_id(escalation_id, tenant)
    if escalation is None:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        )
    if escalation.status in (EscalationStatus.resolved, EscalationStatus.closed):
        raise EscalationConflictError(
            f"Escalation already in status '{escalation.status.value}'",
            details={
                "escalation_id": str(escalation_id),
                "current_status": escalation.status.value,
            },
        )

    try:
        result = await svc.close_escalation(
            escalation_id,
            body.resolution_notes,
            uuid.UUID(admin.sub),
            tenant,
        )
    except NoResultFound as err:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        ) from err

    return EscalationRead.model_validate(result)


@router.get("/{escalation_id}/conversation", response_model=list[MessageResponse])
async def get_escalation_conversation(
    escalation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MessageResponse]:
    """Fetch the conversation history linked to this escalation.

    Used by the back-office to display the chat bubbles for context.
    """
    svc = get_escalation_service()

    escalation = await svc.get_escalation_by_id(escalation_id, tenant)
    if escalation is None:
        raise ResourceNotFoundError(
            f"Escalation not found: {escalation_id}",
            details={"escalation_id": str(escalation_id)},
        )

    messages = await svc.get_conversation_messages(
        escalation.conversation_id,
        tenant,
        limit=limit,
    )
    return [MessageResponse.model_validate(m) for m in messages]
