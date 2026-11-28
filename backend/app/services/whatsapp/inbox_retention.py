"""Redact expired inbox payloads while preserving replay-protection tombstones.

This is staged with the durable inbox. The tenant's configured conversation
retention applies to encrypted ingress content as well. Provider identifiers
and keyed fingerprints remain as pseudonymous tombstones; deleting those
requires a separate replay-protection and institutional retention policy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import case, func, or_, select, update

from app.core.database import get_session_factory
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent

logger = structlog.get_logger()
BATCH_SIZE = 500


async def _redact_tenant(
    tenant_id, slug: str, retention_days: int, now: datetime
) -> dict[str, int]:
    if not 1 <= retention_days <= 3650:
        raise ValueError("Invalid tenant retention period")
    cutoff = now - timedelta(days=retention_days)
    counts = {"messages": 0, "statuses": 0}
    async with get_session_factory()() as session:
        for label, model in (("messages", WhatsAppInboxEvent), ("statuses", WhatsAppStatusEvent)):
            criteria = [
                model.tenant_id == tenant_id,
                model.created_at < cutoff,
                model.redacted_at.is_(None),
            ]
            if model is WhatsAppInboxEvent:
                # A live claim can still be using plaintext. An expired claim
                # becomes uncertain and is fenced before its payload is removed.
                criteria.append(or_(model.state != "processing", model.lease_until <= now))
            ids = (
                (
                    await session.execute(
                        select(model.id)
                        .where(*criteria)
                        .order_by(model.created_at, model.id)
                        .limit(BATCH_SIZE)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            if not ids:
                continue
            if model is WhatsAppInboxEvent:
                values = {
                    "ciphertext": "",
                    # Keep the opaque grouping only while an unresolved event
                    # must block later messages in the same conversation.
                    "sender_fingerprint": case(
                        (model.state.in_(["completed", "resolved"]), None),
                        else_=model.sender_fingerprint,
                    ),
                    "is_opt_out": case(
                        (model.state.in_(["completed", "resolved"]), False),
                        else_=model.is_opt_out,
                    ),
                    "redacted_at": now,
                    "updated_at": func.clock_timestamp(),
                    "state": case(
                        (model.state.in_(["pending", "processing"]), "uncertain"), else_=model.state
                    ),
                    "lease_until": None,
                    "lease_token": None,
                }
            else:
                values = {
                    "ciphertext": "",
                    "redacted_at": now,
                    "updated_at": func.clock_timestamp(),
                    "state": case((model.state == "pending", "uncertain"), else_=model.state),
                }
            result = await session.execute(
                update(model)
                .execution_options(synchronize_session=False)
                .where(model.id.in_(ids), model.tenant_id == tenant_id)
                .values(**values)
            )
            counts[label] = result.rowcount
        if any(counts.values()):
            session.add(
                AuditLog(
                    tenant_slug=slug,
                    user_type="system",
                    action="wa_payload_purge",
                    resource_type="whatsapp_inbox",
                    details={"retention_days": retention_days, **counts},
                )
            )
        await session.commit()
    return counts


async def redact_expired_inbox(ctx: dict) -> dict[str, int]:
    """Process a bounded batch per tenant; failed tenants remain for retry."""
    async with get_session_factory()() as session:
        tenants = (
            await session.execute(
                select(Tenant.id, Tenant.slug, Tenant.conversation_retention_days)
            )
        ).all()
    totals = {"messages": 0, "statuses": 0, "tenants_failed": 0}
    now = datetime.now(UTC)
    for tenant_id, slug, retention_days in tenants:
        try:
            counts = await _redact_tenant(tenant_id, slug, retention_days, now)
            totals["messages"] += counts["messages"]
            totals["statuses"] += counts["statuses"]
        except Exception as exc:
            totals["tenants_failed"] += 1
            logger.error("wa_payload_retention_failed", tenant=slug, error_type=type(exc).__name__)
    logger.info("wa_payload_retention_complete", **totals)
    return totals
