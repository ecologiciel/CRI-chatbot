"""Database primitives for the staged notification outbox.

Nothing invokes these primitives yet. Expired claims require human review:
the provider may have accepted an outbound message before a worker died.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_outbox import NotificationOutboxEvent


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    event_id: uuid.UUID
    history_id: uuid.UUID
    lease_token: uuid.UUID


async def enqueue_notification(
    session: AsyncSession, tenant_id: uuid.UUID, history_id: uuid.UUID
) -> bool:
    """Persist an intent in the caller's transaction, deduplicated by history."""
    result = await session.execute(
        insert(NotificationOutboxEvent)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, history_id=history_id)
        .on_conflict_do_nothing(index_elements=["tenant_id", "history_id"])
        .returning(NotificationOutboxEvent.id)
    )
    return result.scalar_one_or_none() is not None


async def claim_notification(
    session: AsyncSession, tenant_id: uuid.UUID, *, lease_seconds: int = 300
) -> NotificationClaim | None:
    """Claim a pending intent under the caller's transaction and tenant binding."""
    if not 1 <= lease_seconds <= 3600:
        raise ValueError("invalid lease duration")
    stmt = (
        select(NotificationOutboxEvent)
        .where(
            NotificationOutboxEvent.tenant_id == tenant_id,
            NotificationOutboxEvent.state == "pending",
        )
        .order_by(NotificationOutboxEvent.created_at, NotificationOutboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    token = uuid.uuid4()
    row.state = "processing"
    row.lease_token = token
    row.lease_until = func.now() + timedelta(seconds=lease_seconds)
    row.attempts += 1
    row.updated_at = func.now()
    await session.flush()
    return NotificationClaim(row.id, row.history_id, token)


async def finish_notification(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    claim: NotificationClaim,
    *,
    outcome: str,
    outcome_code: str,
) -> bool:
    """Finish only a current, unexpired claim; sent means provider acceptance."""
    if outcome not in {"sent", "skipped", "uncertain"}:
        raise ValueError("invalid outcome")
    if not outcome_code or len(outcome_code) > 64 or not outcome_code.replace("_", "").isalnum():
        raise ValueError("invalid outcome code")
    result = await session.execute(
        update(NotificationOutboxEvent)
        .where(
            NotificationOutboxEvent.tenant_id == tenant_id,
            NotificationOutboxEvent.id == claim.event_id,
            NotificationOutboxEvent.state == "processing",
            NotificationOutboxEvent.lease_token == claim.lease_token,
            NotificationOutboxEvent.lease_until > func.now(),
        )
        .values(
            state=outcome,
            outcome_code=outcome_code,
            lease_token=None,
            lease_until=None,
            updated_at=func.now(),
        )
    )
    return result.rowcount == 1


async def quarantine_expired_notifications(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Never replay an expired send automatically: its outcome is unknown."""
    result = await session.execute(
        update(NotificationOutboxEvent)
        .where(
            NotificationOutboxEvent.tenant_id == tenant_id,
            NotificationOutboxEvent.state == "processing",
            NotificationOutboxEvent.lease_until <= func.now(),
        )
        .values(
            state="uncertain",
            outcome_code="lease_expired",
            lease_token=None,
            lease_until=None,
            updated_at=func.now(),
        )
    )
    return int(result.rowcount)
