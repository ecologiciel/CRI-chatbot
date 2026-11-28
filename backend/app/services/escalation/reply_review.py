"""Audited human decisions on uncertain agent replies; never sends messages."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import lock_active_tenant
from app.models.admin import Admin
from app.models.agent_reply_outbox import AgentReplyOutboxEvent
from app.models.audit import AuditLog
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.services.escalation.reply_outbox import AgentReplyConflictError

ReviewDecision = Literal["confirmed_delivered", "confirmed_not_sent", "unknown_no_retry"]


async def review_agent_reply(
    tenant: TenantContext, escalation_id: uuid.UUID, event_id: uuid.UUID, reviewer_id: uuid.UUID,
    *, action: Literal["follow_up", "resolve"], decision: ReviewDecision | None = None,
) -> str:
    """Record a declaration, not proof of provider delivery or a retry."""
    decisions = {"confirmed_delivered", "confirmed_not_sent", "unknown_no_retry"}
    if ((action == "follow_up" and decision is not None)
            or (action == "resolve" and decision not in decisions)
            or action not in {"follow_up", "resolve"}):
        raise ValueError("Invalid review decision")
    async with get_session_factory()() as session:
        await lock_active_tenant(session, tenant)
        current = (await session.execute(
            select(Tenant.id).where(Tenant.id == tenant.id, Tenant.slug == tenant.slug,
                                    Tenant.status == TenantStatus.active).with_for_update(read=True)
        )).scalar_one_or_none()
        if current is None:
            raise AgentReplyConflictError("Institution indisponible")
        reviewer = (await session.execute(
            select(Admin.id).where(
                Admin.id == reviewer_id, Admin.tenant_id == tenant.id, Admin.is_active.is_(True),
                Admin.role.in_([AdminRole.admin_tenant, AdminRole.supervisor]),
            ).with_for_update(read=True)
        )).scalar_one_or_none()
        if reviewer is None:
            raise AgentReplyConflictError("Agent indisponible ou non autorisé")
        event = (await session.execute(
            select(AgentReplyOutboxEvent).where(
                AgentReplyOutboxEvent.id == event_id, AgentReplyOutboxEvent.tenant_id == tenant.id,
                AgentReplyOutboxEvent.escalation_id == escalation_id,
            ).with_for_update()
        )).scalar_one_or_none()
        if event is None:
            raise AgentReplyConflictError("Demande introuvable")
        allowed = {"uncertain"} if action == "follow_up" else {"uncertain", "follow_up"}
        if event.state not in allowed:
            raise AgentReplyConflictError("État de la demande modifié")
        previous = event.state
        event.state = "follow_up" if action == "follow_up" else "resolved"
        if action == "resolve":
            event.review_decision = decision
            event.reviewed_by = reviewer_id
            event.reviewed_at = func.clock_timestamp()
        event.updated_at = func.clock_timestamp()
        session.add(AuditLog(
            tenant_slug=tenant.slug, user_id=reviewer_id, user_type="admin", action="agent_reply_review",
            resource_type="agent_reply", resource_id=str(event.id),
            details={"previous_state": previous, "action": action, "decision": decision},
        ))
        await session.commit()
        return event.state
