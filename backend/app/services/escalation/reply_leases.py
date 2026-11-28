"""Ordered, single-attempt claims for the staged agent reply outbox.

These primitives do not contact Meta. Expired claims are quarantined, never
returned to the queue: a timeout cannot prove that a provider did not send.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.agent_reply_outbox import AgentReplyOutboxEvent
from app.models.audit import AuditLog
from app.models.tenant import Tenant

_UNRESOLVED = ("pending", "processing", "uncertain", "follow_up")


class AgentReplyLeaseLostError(RuntimeError):
    """The claim expired, changed owner, or was already finalized."""


@dataclass(frozen=True, slots=True)
class AgentReplyClaim:
    id: uuid.UUID
    tenant_id: uuid.UUID
    token: uuid.UUID


def _lease(seconds: int) -> timedelta:
    if not 10 <= seconds <= 900:
        raise ValueError("Invalid agent reply lease")
    return timedelta(seconds=seconds)


async def claim_next_reply(session: AsyncSession, *, lease_seconds: int = 120) -> AgentReplyClaim | None:
    """Claim the earliest unresolved event of a conversation, in one transaction."""
    duration = _lease(lease_seconds)
    earlier = aliased(AgentReplyOutboxEvent)
    event = AgentReplyOutboxEvent
    candidate = (await session.execute(
        select(event).where(
            event.state == "pending", event.attempts == 0,
            ~exists(select(1).where(
                earlier.tenant_id == event.tenant_id,
                earlier.conversation_id == event.conversation_id,
                earlier.sequence < event.sequence,
                earlier.state.in_(_UNRESOLVED),
            )),
        ).order_by(event.sequence).with_for_update(skip_locked=True).limit(1)
    )).scalar_one_or_none()
    if candidate is None:
        return None
    token = uuid.uuid4()
    candidate.state = "processing"
    candidate.attempts = 1
    candidate.lease_token = token
    candidate.lease_until = func.clock_timestamp() + duration
    candidate.updated_at = func.clock_timestamp()
    await session.flush()
    return AgentReplyClaim(candidate.id, candidate.tenant_id, token)


async def quarantine_reply(
    session: AsyncSession, claim: AgentReplyClaim, *, precondition_failed: bool = False,
) -> None:
    """Quarantine an ambiguous result; acceptance requires the execution transaction."""
    result = await session.execute(
        update(AgentReplyOutboxEvent).where(
            AgentReplyOutboxEvent.id == claim.id,
            AgentReplyOutboxEvent.tenant_id == claim.tenant_id,
            AgentReplyOutboxEvent.state == "processing",
            AgentReplyOutboxEvent.lease_token == claim.token,
            AgentReplyOutboxEvent.lease_until > func.clock_timestamp(),
        ).values(
            state="uncertain",
            outcome_code="precondition_changed" if precondition_failed else "provider_unconfirmed",
            provider_message_id=None, lease_token=None, lease_until=None,
            updated_at=func.clock_timestamp(),
        ).returning(AgentReplyOutboxEvent.id)
    )
    if result.scalar_one_or_none() is None:
        raise AgentReplyLeaseLostError("Agent reply lease unavailable")


async def quarantine_expired_replies(session: AsyncSession, *, limit: int = 100) -> int:
    """Move expired claims to review without ever scheduling another send."""
    if not 1 <= limit <= 500:
        raise ValueError("Invalid quarantine batch size")
    rows = (await session.execute(
        select(AgentReplyOutboxEvent.id, Tenant.slug)
        .join(Tenant, Tenant.id == AgentReplyOutboxEvent.tenant_id)
        .where(
            AgentReplyOutboxEvent.state == "processing",
            AgentReplyOutboxEvent.lease_until <= func.clock_timestamp(),
        ).order_by(AgentReplyOutboxEvent.lease_until, AgentReplyOutboxEvent.id)
        .with_for_update(of=AgentReplyOutboxEvent, skip_locked=True).limit(limit)
    )).all()
    if not rows:
        return 0
    ids = [row.id for row in rows]
    result = await session.execute(
        update(AgentReplyOutboxEvent).where(
            AgentReplyOutboxEvent.id.in_(ids), AgentReplyOutboxEvent.state == "processing",
        ).values(state="uncertain", outcome_code="lease_expired", lease_token=None,
                 lease_until=None, updated_at=func.clock_timestamp())
    )
    for row in rows:
        session.add(AuditLog(
            tenant_slug=row.slug, user_type="system", action="agent_reply_expired",
            resource_type="agent_reply", resource_id=str(row.id),
        ))
    await session.flush()
    return result.rowcount
