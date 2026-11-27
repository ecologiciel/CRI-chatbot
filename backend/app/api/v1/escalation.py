"""Escalation API — list, assign, respond, close escalations.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Requires supervisor or admin_tenant role for back-office access.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.exceptions import EscalationConflictError, ResourceNotFoundError
from app.core.rbac import require_role
from app.core.redis import get_redis
from app.core.tenant import TenantContext, get_current_tenant
from app.models.agent_reply_outbox import AgentReplyOutboxEvent
from app.models.enums import (
    AdminRole,
    EscalationPriority,
    EscalationStatus,
)
from app.schemas.auth import AdminTokenPayload
from app.schemas.conversation import MessageResponse
from app.schemas.escalation import (
    AgentReplyRequest,
    EscalationList,
    EscalationRead,
    EscalationResolve,
    EscalationRespond,
    EscalationStats,
)
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation import get_escalation_service
from app.services.escalation.reply_outbox import (
    AgentReplyConflictError,
    register_agent_reply,
)
from app.services.escalation.reply_presence import HEARTBEAT_KEY

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


@router.get("/reply-mode")
async def reply_mode(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> dict:
    """Report configuration only; this is not a worker or delivery check."""
    enabled = get_settings().agent_reply_outbox_enabled
    seen = None
    if enabled:
        try:
            seen = bool(await get_redis().exists(HEARTBEAT_KEY))
        except Exception:
            pass
    return {"durable": enabled, "worker_seen": seen}


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
    if get_settings().agent_reply_outbox_enabled:
        raise EscalationConflictError("Utilisez la file de réponses durables")
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


@router.post("/{escalation_id}/reply-requests", status_code=202)
async def create_reply_request(
    escalation_id: uuid.UUID,
    body: AgentReplyRequest,
    response: Response,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> dict:
    """Record an encrypted intention; acceptance is not provider delivery."""
    settings = get_settings()
    if not settings.agent_reply_outbox_enabled:
        raise HTTPException(status_code=503, detail="File de réponses désactivée")
    try:
        worker_seen = bool(await get_redis().exists(HEARTBEAT_KEY))
    except Exception:
        worker_seen = False
    if not worker_seen:
        raise HTTPException(status_code=503, detail="Worker de réponses indisponible")
    cipher = VersionedEnvelopeService(get_session_factory(), settings.kms_master_key)
    try:
        result = await register_agent_reply(
            tenant, escalation_id, uuid.UUID(admin.sub), body.request_key, body.message, cipher=cipher,
        )
    except AgentReplyConflictError as exc:
        raise EscalationConflictError(str(exc)) from exc
    except ValueError:
        raise HTTPException(status_code=422, detail="Réponse invalide") from None
    response.status_code = 202 if result.created else 200
    return {"id": str(result.id), "state": result.state, "created": result.created}


@router.get("/{escalation_id}/reply-requests/{request_key}")
async def get_reply_request(
    escalation_id: uuid.UUID,
    request_key: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ESCALATION_ROLES)),
) -> dict:
    """Retrieve the requesting agent's status without exposing content."""
    async with get_session_factory()() as session:
        event = (await session.execute(
            select(AgentReplyOutboxEvent).where(
                AgentReplyOutboxEvent.tenant_id == tenant.id,
                AgentReplyOutboxEvent.escalation_id == escalation_id,
                AgentReplyOutboxEvent.request_key == request_key,
                AgentReplyOutboxEvent.actor_id == uuid.UUID(admin.sub),
            )
        )).scalar_one_or_none()
    if event is None:
        raise ResourceNotFoundError("Demande introuvable")
    return {"id": str(event.id), "state": event.state, "outcome_code": event.outcome_code,
            "created_at": event.created_at, "redacted_at": event.redacted_at}


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
