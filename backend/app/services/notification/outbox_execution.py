"""Staged execution of one durable notification; not scheduled in production."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select

from app.core.tenant import TenantContext
from app.models.dossier import Dossier, DossierHistory
from app.services.notification.outbox import (
    NotificationClaim,
    claim_notification,
    finish_notification,
    quarantine_expired_notifications,
)
from app.services.notification.service import DossierChangeEvent, NotificationService

logger = structlog.get_logger()
_SKIP_REASONS = {
    "same_status",
    "no_matching_rule",
    "no_contact_id",
    "contact_not_found",
    "opted_out",
    "no_phone",
    "opted_out_after_recheck",
    "contact_not_found_after_recheck",
    "recipient_changed",
    "dossier_superseded",
}


async def _load_change(
    tenant: TenantContext, claim: NotificationClaim
) -> DossierChangeEvent | None:
    """Resolve references solely through the institution's own database schema."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(DossierHistory, Dossier)
            .join(Dossier, Dossier.id == DossierHistory.dossier_id)
            .where(
                DossierHistory.id == claim.history_id,
                DossierHistory.field_changed == "statut",
                DossierHistory.dossier_id == claim.dossier_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        history, dossier = row
        if history.old_value is None or history.new_value is None:
            return None
        return DossierChangeEvent(
            dossier_id=str(dossier.id),
            numero=dossier.numero,
            contact_id=str(claim.contact_id) if claim.contact_id else None,
            old_statut=history.old_value,
            new_statut=history.new_value,
            sync_log_id=str(history.sync_log_id) if history.sync_log_id else None,
        )


async def process_one_notification(
    tenant: TenantContext,
    service: NotificationService,
    *,
    lease_seconds: int = 300,
    timeout_seconds: float = 90,
) -> str:
    """Claim, attempt once, then fence finalization; never retry an ambiguous send."""
    if timeout_seconds <= 0 or timeout_seconds >= lease_seconds:
        raise ValueError("timeout must be shorter than the lease")
    async with tenant.db_session() as session:
        await quarantine_expired_notifications(session, tenant.id)
        claim = await claim_notification(session, tenant.id, lease_seconds=lease_seconds)
    if claim is None:
        return "empty"

    outcome, code, message_id = "uncertain", "processing_error", None
    try:
        async with asyncio.timeout(timeout_seconds):
            event = await _load_change(tenant, claim)
            if event is None:
                code = "history_unavailable"
            else:
                # The database claim handles idempotence; the old Redis NX key
                # is neither a durable receipt nor scoped to the history event.
                result: dict[str, Any] = await service.send_notification(
                    event, tenant, durable=True, durable_claim=claim
                )
                status = result.get("status")
                if status == "sent" and isinstance(result.get("wamid"), str):
                    candidate = result["wamid"]
                    if 0 < len(candidate) <= 255:
                        outcome, code, message_id = "sent", "provider_accepted", candidate
                elif status == "skipped":
                    reason = result.get("reason")
                    if reason in _SKIP_REASONS:
                        outcome, code = "skipped", reason
                    else:
                        code = "unknown_skip_reason"
                elif status == "unconfirmed":
                    code = "provider_unconfirmed"
    except TimeoutError:
        code = "processing_timeout"
    except Exception as exc:
        logger.warning("notification_outbox_execution_error", error_type=type(exc).__name__)

    async with tenant.db_session() as session:
        finished = await finish_notification(
            session,
            tenant.id,
            claim,
            outcome=outcome,
            outcome_code=code,
            provider_message_id=message_id,
        )
    return outcome if finished else "lease_lost"
