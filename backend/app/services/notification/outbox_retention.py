"""Remove expired outbox identifiers without removing ordering tombstones.

References to tenant, dossier and history remain pseudonymous. PostgreSQL WAL
and backups are governed separately; this task does not erase those copies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import case, func, or_, select, update

from app.core.database import get_session_factory
from app.models.audit import AuditLog
from app.models.notification_outbox import NotificationOutboxEvent as Event
from app.models.tenant import Tenant

logger = structlog.get_logger()
BATCH_SIZE = 500


async def redact_tenant_outbox(tenant_id, slug: str, retention_days: int, now: datetime) -> int:
    """Redact one bounded batch atomically with its audit record."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("Invalid tenant retention period")
    async with get_session_factory()() as session:
        ids = (
            (
                await session.execute(
                    select(Event.id)
                    .where(
                        Event.tenant_id == tenant_id,
                        Event.created_at < now - timedelta(days=retention_days),
                        Event.redacted_at.is_(None),
                        or_(
                            Event.state != "processing", Event.lease_until <= func.clock_timestamp()
                        ),
                    )
                    .order_by(Event.created_at, Event.id)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            return 0
        result = await session.execute(
            update(Event)
            .where(Event.id.in_(ids), Event.tenant_id == tenant_id)
            .execution_options(synchronize_session=False)
            .values(
                contact_id=None,
                provider_message_id=None,
                redacted_at=now,
                state=case(
                    (Event.state.in_(["pending", "processing"]), "uncertain"), else_=Event.state
                ),
                outcome_code=case(
                    (Event.state.in_(["pending", "processing"]), "retention_expired"),
                    else_=Event.outcome_code,
                ),
                lease_token=None,
                lease_until=None,
                updated_at=func.clock_timestamp(),
            )
        )
        count = int(result.rowcount)
        session.add(
            AuditLog(
                tenant_slug=slug,
                user_type="system",
                action="notif_outbox_purge",
                resource_type="notification_outbox",
                details={"retention_days": retention_days, "count": count},
            )
        )
        await session.commit()
        return count


async def redact_expired_outbox(ctx: dict) -> dict[str, int]:
    async with get_session_factory()() as session:
        tenants = (
            await session.execute(
                select(Tenant.id, Tenant.slug, Tenant.conversation_retention_days)
            )
        ).all()
    totals = {"redacted": 0, "tenants_failed": 0}
    now = datetime.now(UTC)
    for tenant_id, slug, days in tenants:
        try:
            totals["redacted"] += await redact_tenant_outbox(tenant_id, slug, days, now)
        except Exception as exc:
            totals["tenants_failed"] += 1
            logger.error(
                "notification_retention_failed", tenant=slug, error_type=type(exc).__name__
            )
    logger.info("notification_retention_complete", **totals)
    return totals
