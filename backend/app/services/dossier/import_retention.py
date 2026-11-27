"""Opt-in deletion of terminal import snapshots with durable audit intent.

Original watched files, orphaned uploads, database rows, object versions and
backups are outside this operation. Uncertain or active imports are retained.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.minio import get_minio
from app.core.tenant import TenantContext
from app.models.audit import AuditLog
from app.models.dossier_import_request import DossierImportRequest as Request
from app.models.tenant import Tenant

logger = structlog.get_logger()
BATCH_SIZE = 25


async def purge_one_import_source(tenant_id: uuid.UUID, slug: str, days: int, storage) -> str:
    """Persist an intent, delete an immutable generated key, then record completion.

    A crash or lost response leaves the intent for a later idempotent delete.
    Neither object content nor object key is emitted to audit logs.
    """
    if not 1 <= days <= 3650:
        raise ValueError("invalid import retention period")
    bucket = TenantContext(tenant_id, slug, slug, "active", None).minio_bucket
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(Request)
                .where(
                    Request.tenant_id == tenant_id,
                    Request.state.in_(("completed", "failed")),
                    Request.source_purge_state.in_(("present", "deleting")),
                    Request.updated_at < cutoff,
                )
                .order_by(Request.updated_at, Request.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return "empty"
        request_id, key = row.id, row.object_key
        prefix = f"imports/requests/{request_id.hex}/source."
        if key not in {prefix + ext for ext in ("csv", "xls", "xlsx")}:
            raise ValueError("invalid stored import object key")
        if row.source_purge_state == "present":
            row.source_purge_state = "deleting"
            session.add(
                AuditLog(
                    tenant_slug=slug,
                    user_type="system",
                    action="import_purge_intent",
                    resource_type="dossier_import_request",
                    resource_id=str(request_id),
                    details={"retention_days": days},
                )
            )
            await session.commit()
        else:
            await session.rollback()

    await storage.remove_object(bucket, key)

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(Request)
                .where(Request.id == request_id, Request.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.source_purge_state != "deleting":
            return "already_recorded"
        row.source_purge_state = "deleted"
        row.source_purged_at = datetime.now(UTC)
        session.add(
            AuditLog(
                tenant_slug=slug,
                user_type="system",
                action="import_purge_done",
                resource_type="dossier_import_request",
                resource_id=str(request_id),
                details={"retention_days": days},
            )
        )
        await session.commit()
    return "deleted"


async def purge_import_sources(ctx: dict) -> dict[str, int]:
    settings = get_settings()
    totals = {"deleted": 0, "tenants_failed": 0}
    if not settings.dossier_durable_imports_enabled or settings.dossier_import_retention_days == 0:
        return totals
    async with get_session_factory()() as session:
        tenants = (await session.execute(select(Tenant.id, Tenant.slug))).all()
    storage = get_minio()
    for tenant_id, slug in tenants:
        try:
            for _ in range(BATCH_SIZE):
                result = await purge_one_import_source(
                    tenant_id, slug, settings.dossier_import_retention_days, storage
                )
                if result == "empty":
                    break
                totals["deleted"] += int(result == "deleted")
        except Exception as exc:
            totals["tenants_failed"] += 1
            logger.error(
                "import_source_retention_failed", tenant=slug, error_type=type(exc).__name__
            )
    return totals
