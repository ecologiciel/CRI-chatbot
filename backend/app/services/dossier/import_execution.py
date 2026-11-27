"""Execute one staged durable import; not yet scheduled by a production worker."""

from __future__ import annotations

import asyncio

import structlog

from app.core.tenant import TenantContext
from app.services.dossier.import_requests import (
    LostImportLeaseError,
    claim_import,
    finish_import,
    quarantine_expired_imports,
)

logger = structlog.get_logger()


async def process_one_durable_import(
    tenant: TenantContext, *, lease_seconds: int = 900, timeout_seconds: float = 660
) -> str:
    """Claim from PostgreSQL and attempt once, regardless of Redis job state."""
    if timeout_seconds <= 0 or timeout_seconds >= lease_seconds:
        raise ValueError("timeout must be shorter than the lease")
    async with tenant.db_session() as session:
        await quarantine_expired_imports(session, tenant.id)
        claim = await claim_import(session, tenant.id, lease_seconds=lease_seconds)
    if claim is None:
        return "empty"
    try:
        from app.workers.import_dossier import task_import_dossier

        async with asyncio.timeout(timeout_seconds):
            result = await task_import_dossier(
                {},
                claim.object_key,
                str(claim.sync_config_id) if claim.sync_config_id else None,
                tenant.slug,
                str(claim.requested_by) if claim.requested_by else None,
                durable_claim=claim,
            )
        outcome = {"completed": "completed", "skipped": "completed", "failed": "failed"}.get(
            result.get("status")
        )
        if outcome is None:
            raise ValueError("unexpected import outcome")
        return outcome
    except TimeoutError:
        code = "processing_timeout"
    except Exception as exc:
        code = "processing_error"
        logger.warning(
            "durable_import_execution_error", tenant=tenant.slug, error_type=type(exc).__name__
        )
    try:
        async with tenant.db_session() as session:
            await finish_import(
                session, claim, state="uncertain", outcome_code=code, sync_log_id=None
            )
        return "uncertain"
    except LostImportLeaseError:
        # The task may already have finalized or the lease was quarantined.
        return "already_finalized_or_lease_lost"
