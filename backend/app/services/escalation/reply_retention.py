"""Bounded terminal-payload redaction, retaining idempotency tombstones.

This does not delete copies in conversation messages, PostgreSQL WAL, logs or
backups. Unresolved events remain actionable and must be monitored separately.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select, update

from app.core.database import get_session_factory
from app.models.agent_reply_outbox import AgentReplyOutboxEvent as Event
from app.models.audit import AuditLog
from app.models.tenant import Tenant

logger = structlog.get_logger()
TERMINAL = ("accepted", "resolved", "canceled")
UNRESOLVED = ("pending", "processing", "uncertain", "follow_up")
BATCH_SIZE = 500


async def redact_tenant_replies(tenant_id, slug: str, retention_days: int, now: datetime) -> dict[str, int]:
    """Redact terminal records and audit atomically, never modifying unresolved work."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("Invalid tenant retention period")
    cutoff = now - timedelta(days=retention_days)
    async with get_session_factory()() as session:
        ids = (await session.execute(
            select(Event.id).where(
                Event.tenant_id == tenant_id, Event.state.in_(TERMINAL),
                Event.redacted_at.is_(None), Event.updated_at < cutoff,
            ).order_by(Event.updated_at, Event.id).limit(BATCH_SIZE).with_for_update(skip_locked=True)
        )).scalars().all()
        overdue = int(await session.scalar(
            select(func.count()).select_from(Event).where(
                Event.tenant_id == tenant_id, Event.state.in_(UNRESOLVED), Event.updated_at < cutoff,
            )
        ) or 0)
        count = 0
        if ids:
            result = await session.execute(
                update(Event).where(Event.tenant_id == tenant_id, Event.id.in_(ids))
                .execution_options(synchronize_session=False)
                .values(ciphertext="", contact_id=None, phone_number_id=None,
                        recipient_fingerprint=None, provider_message_id=None,
                        redacted_at=now, updated_at=func.clock_timestamp())
            )
            count = int(result.rowcount)
            session.add(AuditLog(
                tenant_slug=slug, user_type="system", action="agent_reply_purge",
                resource_type="agent_reply", details={"retention_days": retention_days, "count": count},
            ))
        await session.commit()
        return {"redacted": count, "overdue_unresolved": overdue}


async def redact_expired_agent_replies(ctx: dict) -> dict[str, int]:
    """Process bounded batches per tenant, including inactive institutions."""
    async with get_session_factory()() as session:
        tenants = (await session.execute(
            select(Tenant.id, Tenant.slug, Tenant.conversation_retention_days)
        )).all()
    totals = {"redacted": 0, "overdue_unresolved": 0, "tenants_failed": 0}
    now = datetime.now(UTC)
    for tenant_id, slug, days in tenants:
        try:
            counts = await redact_tenant_replies(tenant_id, slug, days, now)
            for key, count in counts.items():
                totals[key] += count
            if counts["overdue_unresolved"]:
                logger.warning("agent_reply_retention_review_overdue", tenant=slug,
                               count=counts["overdue_unresolved"])
        except Exception as exc:
            totals["tenants_failed"] += 1
            logger.error("agent_reply_retention_failed", tenant=slug, error_type=type(exc).__name__)
    logger.info("agent_reply_retention_complete", **totals)
    return totals
