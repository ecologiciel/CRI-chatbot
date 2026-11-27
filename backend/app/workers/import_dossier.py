"""ARQ worker for dossier import from MinIO (Excel/CSV).

Runs as a separate process: arq app.workers.import_dossier.WorkerSettings

Tasks:
    task_import_dossier       — import a single file (download, validate, parse, import)
    task_watch_import_folder  — scan tenant's MinIO pending folder, enqueue new files
    task_scheduled_import_all — cron: iterate active tenants, enqueue watch tasks

Notifications:
    Status changes (field_changed="statut") are published to Redis list
    ``{slug}:notification:dossier_changes`` for the downstream notification worker.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import select

from app.core.arq import DOSSIER_IMPORT_QUEUE
from app.core.config import get_settings
from app.models.enums import SyncSourceType, SyncStatus, TenantStatus

logger = structlog.get_logger()

if TYPE_CHECKING:
    from app.services.dossier.import_requests import ImportClaim


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the import worker process."""
    if not get_settings().dossier_import_worker_enabled:
        raise RuntimeError("Dossier import worker is disabled")
    if (
        get_settings().dossier_durable_imports_enabled
        and not get_settings().dossier_notification_outbox_enabled
    ):
        raise RuntimeError("Durable imports require the transactional notification outbox")
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.minio import init_minio
    from app.core.redis import init_redis
    from app.services.crypto.startup_guard import verify_kms_on_startup

    setup_logging()
    get_engine()
    await verify_kms_on_startup()
    await init_redis()
    init_minio()
    logger.info("import_dossier_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.redis import close_redis

    await close_redis()
    await close_engine()
    logger.info("import_dossier_worker_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IMPORT_EXTENSIONS: set[str] = {".xlsx", ".xls", ".csv"}


def _source_type_from_ext(ext: str) -> SyncSourceType:
    """Map file extension to SyncSourceType."""
    return SyncSourceType.csv if ext == ".csv" else SyncSourceType.excel


# ---------------------------------------------------------------------------
# Task 1 — Import a single file
# ---------------------------------------------------------------------------


async def task_import_dossier(
    ctx: dict,
    file_path: str,
    sync_config_id: str | None,
    tenant_slug: str,
    triggered_by: str | None = None,
    *,
    durable_claim: ImportClaim | None = None,
) -> dict:
    """Download file from MinIO, validate, parse, and import dossiers.

    Args:
        ctx: ARQ context (contains redis pool).
        file_path: Relative path inside the tenant's MinIO bucket
            (e.g. ``imports/pending/dossiers_2024.xlsx``).
        sync_config_id: UUID string of the SyncConfig to use, or None
            for auto-detection (first active config).
        tenant_slug: Tenant slug for resolution.
        triggered_by: UUID string of the admin who triggered the import,
            or None for automated/cron imports.

    Returns:
        Dict with status, sync_log_id, row counts, and notifications_published.
    """
    from app.core.minio import get_object_bytes
    from app.core.tenant import TenantResolver
    from app.models.sync import SyncConfig, SyncLog
    from app.services.dossier.import_service import MAX_FILE_SIZE_MB, get_dossier_import_service

    start = time.monotonic()
    ext = PurePosixPath(file_path).suffix.lower()
    log = logger.bind(
        task="import_dossier",
        tenant=tenant_slug,
        file_path=file_path,
    )
    log.info("task_start")

    # 1. Resolve tenant
    tenant = await TenantResolver.from_slug(tenant_slug)
    if get_settings().dossier_durable_imports_enabled is True and durable_claim is None:
        raise ValueError("legacy import job rejected while durable imports are enabled")
    if durable_claim is not None and (
        durable_claim.tenant_id != tenant.id
        or durable_claim.object_key != file_path
        or (str(durable_claim.sync_config_id) if durable_claim.sync_config_id else None)
        != sync_config_id
        or (str(durable_claim.requested_by) if durable_claim.requested_by else None) != triggered_by
        or not get_settings().dossier_notification_outbox_enabled
    ):
        raise ValueError("durable import claim mismatch or notification outbox disabled")

    # 2. Create SyncLog (status=pending)
    source_type = _source_type_from_ext(ext)
    file_name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

    async with tenant.db_session() as session:
        sync_log = SyncLog(
            source_type=source_type,
            file_name=file_name,
            status=SyncStatus.pending,
            triggered_by=uuid.UUID(triggered_by) if triggered_by else None,
        )
        session.add(sync_log)
        await session.flush()
        sync_log_id = sync_log.id

    log = log.bind(sync_log_id=str(sync_log_id))

    # Download errors must also mark the sync attempt as failed.
    tmp_path: str | None = None
    try:
        file_bytes = await get_object_bytes(
            tenant.minio_bucket, file_path, max_bytes=MAX_FILE_SIZE_MB * 1024 * 1024
        )
        if (
            durable_claim is not None
            and hashlib.sha256(file_bytes).hexdigest() != durable_claim.content_sha256
        ):
            raise ValueError("Import request integrity check failed")
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            tmp.write(file_bytes)
        if file_path.startswith("imports/staged/"):
            match = re.fullmatch(r"imports/staged/([0-9a-f]{64})/source\.(xlsx|xls|csv)", file_path)
            if match is None or hashlib.sha256(file_bytes).hexdigest() != match.group(1):
                raise ValueError("Import snapshot integrity check failed")
        import_service = get_dossier_import_service()

        # 4. Validate file (extension, size, hash, duplicate check)
        validation = await import_service.validate_file(tmp_path, tenant)

        if validation.is_duplicate:
            async with tenant.db_session() as session:
                sl = await session.get(SyncLog, sync_log_id)
                if sl:
                    sl.status = SyncStatus.completed
                    sl.file_hash = validation.file_hash
                    sl.completed_at = datetime.now(UTC)
                    sl.error_details = {"skipped": "duplicate hash"}
                if durable_claim is not None:
                    if sl is None:
                        raise ValueError("durable import requires a sync log")
                    from app.services.dossier.import_requests import finish_import

                    await finish_import(
                        session,
                        durable_claim,
                        state="completed",
                        outcome_code="duplicate",
                        sync_log_id=sync_log_id,
                    )
            log.info("import_skipped_duplicate", file_hash=validation.file_hash)
            return {
                "status": "skipped",
                "reason": "duplicate_hash",
                "sync_log_id": str(sync_log_id),
            }

        if not validation.is_valid:
            async with tenant.db_session() as session:
                sl = await session.get(SyncLog, sync_log_id)
                if sl:
                    sl.status = SyncStatus.failed
                    sl.completed_at = datetime.now(UTC)
                    sl.error_details = {"error": validation.error}
                if durable_claim is not None:
                    if sl is None:
                        raise ValueError("durable import requires a sync log")
                    from app.services.dossier.import_requests import finish_import

                    await finish_import(
                        session,
                        durable_claim,
                        state="failed",
                        outcome_code="validation_failed",
                        sync_log_id=sync_log_id,
                    )
            log.warning("import_validation_failed", error=validation.error)
            return {"status": "failed", "reason": validation.error, "sync_log_id": str(sync_log_id)}

        # Update SyncLog with file hash
        async with tenant.db_session() as session:
            sl = await session.get(SyncLog, sync_log_id)
            if sl:
                sl.file_hash = validation.file_hash

        # 5. Load SyncConfig for column mapping
        column_mapping: dict | None = None
        async with tenant.db_session() as session:
            if sync_config_id:
                result = await session.execute(
                    select(SyncConfig).where(SyncConfig.id == uuid.UUID(sync_config_id)),
                )
            else:
                result = await session.execute(
                    select(SyncConfig).where(SyncConfig.is_active.is_(True)).limit(1),
                )
            config = result.scalar_one_or_none()
            if sync_config_id and (config is None or not config.is_active):
                raise ValueError("import configuration is unavailable or inactive")
            if config and config.column_mapping:
                column_mapping = config.column_mapping

        # 6. Parse file
        if ext == ".csv":
            rows = import_service.parse_csv(tmp_path, column_mapping)
        else:
            rows = import_service.parse_excel(tmp_path, column_mapping)

        # 7. Sanitize
        rows = [import_service.sanitize_row(row) for row in rows]

        # 8. Import dossiers (handles SyncLog running → completed internally)
        import_kwargs = {
            "durable_notifications": get_settings().dossier_notification_outbox_enabled
        }
        if durable_claim is not None:
            import_kwargs["durable_claim"] = durable_claim
        report = await import_service.import_dossiers(rows, sync_log_id, tenant, **import_kwargs)
        notifications_published = report.notifications_enqueued

        duration = round(time.monotonic() - start, 1)
        log.info(
            "import_complete",
            rows_total=report.rows_total,
            rows_imported=report.rows_imported,
            rows_updated=report.rows_updated,
            rows_errored=report.rows_errored,
            notifications=notifications_published,
            duration_s=duration,
        )
        return {
            "status": "completed",
            "sync_log_id": str(report.sync_log_id),
            "rows_total": report.rows_total,
            "rows_imported": report.rows_imported,
            "rows_updated": report.rows_updated,
            "rows_errored": report.rows_errored,
            "notifications_published": notifications_published,
            "duration_seconds": report.duration_seconds,
        }

    except Exception as exc:
        duration = round(time.monotonic() - start, 1)
        log.error("import_dossier_failed", error_type=type(exc).__name__, duration_s=duration)

        # Best-effort: mark SyncLog as failed
        try:
            from app.core.tenant import TenantResolver

            t = await TenantResolver.from_slug(tenant_slug)
            async with t.db_session() as session:
                sl = await session.get(SyncLog, sync_log_id)
                if sl and sl.status != SyncStatus.failed:
                    sl.status = SyncStatus.failed
                    sl.completed_at = datetime.now(UTC)
                    sl.error_details = (
                        {"error_type": type(exc).__name__}
                        if durable_claim is not None
                        else {"error": str(exc)[:500]}
                    )
                if durable_claim is not None:
                    from app.services.dossier.import_requests import finish_import

                    await finish_import(
                        session,
                        durable_claim,
                        state="uncertain",
                        outcome_code="processing_error",
                        sync_log_id=sync_log_id,
                    )
        except Exception:
            log.warning("failed_to_set_error_status")

        raise

    finally:
        # Always clean up the temp file
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Task 2 — Watch MinIO folder for new files
# ---------------------------------------------------------------------------


async def task_watch_import_folder(
    ctx: dict,
    tenant_slug: str,
) -> dict:
    """Scan tenant's MinIO pending folder, enqueue new files for import.

    Args:
        ctx: ARQ context (contains ArqRedis for job enqueueing).
        tenant_slug: Tenant slug for resolution.

    Returns:
        Dict with files_found, files_enqueued, files_skipped counts.
    """
    from app.core.minio import get_minio, get_object_bytes
    from app.core.tenant import TenantResolver
    from app.models.sync import SyncConfig, SyncLog
    from app.services.dossier.import_service import MAX_FILE_SIZE_MB

    log = logger.bind(task="watch_import_folder", tenant=tenant_slug)
    log.info("task_start")

    # 1. Resolve tenant
    tenant = await TenantResolver.from_slug(tenant_slug)

    # 2. Load active SyncConfig → watched_folder
    sync_config_id: str | None = None
    async with tenant.db_session() as session:
        result = await session.execute(
            select(SyncConfig).where(SyncConfig.is_active.is_(True)).limit(1),
        )
        config = result.scalar_one_or_none()

    watched_folder = "imports/pending/"
    if config:
        sync_config_id = str(config.id)
        if config.watched_folder:
            watched_folder = config.watched_folder

    # 3. List objects in MinIO
    minio = get_minio()
    bucket = tenant.minio_bucket

    # miniopy_async.list_objects returns an async iterator (not a coroutine)
    objects = minio.list_objects(bucket, prefix=watched_folder, recursive=False)
    files_to_process = []
    async for obj in objects:
        if obj.object_name.startswith(("imports/direct/", "imports/staged/", "imports/requests/")):
            continue
        ext = PurePosixPath(obj.object_name).suffix.lower()
        if ext in _IMPORT_EXTENSIONS:
            files_to_process.append(obj)

    files_found = len(files_to_process)
    files_enqueued = 0
    files_skipped = 0

    # 4. Process each file
    for obj in files_to_process:
        try:
            # Download and compute SHA-256
            file_bytes = await get_object_bytes(
                bucket, obj.object_name, max_bytes=MAX_FILE_SIZE_MB * 1024 * 1024
            )
            if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise ValueError("Import source exceeds maximum size")
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # Check if hash already imported
            async with tenant.db_session() as session:
                existing = await session.execute(
                    select(SyncLog.id).where(
                        SyncLog.file_hash == file_hash,
                        SyncLog.status == SyncStatus.completed,
                    ),
                )
                if existing.scalar_one_or_none() is not None:
                    log.debug("file_already_imported", file=obj.object_name, hash=file_hash)
                    files_skipped += 1
                    # Keep the source: it may have changed since it was read.
                    continue

            # The snapshot contains exactly the bytes hashed above. Keep the
            # source untouched until a separate, safe retention process exists.
            ext = PurePosixPath(obj.object_name).suffix.lower()
            if get_settings().dossier_durable_imports_enabled:
                from app.services.dossier.import_requests import (
                    find_existing_import,
                    register_import,
                )

                config_uuid = uuid.UUID(sync_config_id) if sync_config_id else None
                async with tenant.db_session() as session:
                    existing_id = await find_existing_import(
                        session, tenant.id, file_hash, config_uuid
                    )
                if existing_id is not None:
                    files_skipped += 1
                    continue
                request_id = uuid.uuid4()
                snapshot_path = f"imports/requests/{request_id.hex}/source{ext}"
                await minio.put_object(
                    bucket, snapshot_path, data=io.BytesIO(file_bytes), length=len(file_bytes)
                )
                async with tenant.db_session() as session:
                    _, created = await register_import(
                        session,
                        request_id=request_id,
                        tenant_id=tenant.id,
                        object_key=snapshot_path,
                        content_sha256=file_hash,
                        sync_config_id=config_uuid,
                        requested_by=None,
                    )
                    if created:
                        from app.models.audit import AuditLog

                        session.add(
                            AuditLog(
                                tenant_slug=tenant.slug,
                                user_type="system",
                                action="dossier_import_req",
                                resource_type="dossier_import_request",
                                resource_id=str(request_id),
                                details={"source": "watched_folder"},
                            )
                        )
                files_enqueued += int(created)
                files_skipped += int(not created)
                continue
            snapshot_path = f"imports/staged/{file_hash}/source{ext}"
            await minio.put_object(
                bucket, snapshot_path, data=io.BytesIO(file_bytes), length=len(file_bytes)
            )
            key = hashlib.sha256(
                f"{tenant_slug}\0{obj.object_name}\0{file_hash}".encode()
            ).hexdigest()
            job = await ctx["redis"].enqueue_job(
                "task_import_dossier",
                snapshot_path,
                sync_config_id,
                tenant_slug,
                None,  # triggered_by (automated)
                _job_id=f"dossier-import-{key}",
                _queue_name=DOSSIER_IMPORT_QUEUE,
            )
            files_enqueued += int(job is not None)

        except Exception as exc:
            log.error(
                "watch_file_error",
                file=obj.object_name,
                error=str(exc),
            )
            # Continue with next file — one error shouldn't block others

    log.info(
        "watch_complete",
        files_found=files_found,
        files_enqueued=files_enqueued,
        files_skipped=files_skipped,
    )
    return {
        "status": "ok",
        "tenant": tenant_slug,
        "files_found": files_found,
        "files_enqueued": files_enqueued,
        "files_skipped": files_skipped,
    }


# ---------------------------------------------------------------------------
# Task 3 — Scheduled import (cron: daily 06:00 UTC)
# ---------------------------------------------------------------------------


async def task_scheduled_import_all(ctx: dict) -> dict:
    """Iterate active tenants with cron-enabled SyncConfigs, enqueue watch tasks.

    Called by ARQ cron daily at 06:00 UTC.

    Args:
        ctx: ARQ context (contains ArqRedis for job enqueueing).

    Returns:
        Dict with tenants_checked and tenants_enqueued counts.
    """
    from app.core.database import get_session_factory
    from app.core.tenant import TenantResolver
    from app.models.sync import SyncConfig
    from app.models.tenant import Tenant

    log = logger.bind(task="scheduled_import_all")
    log.info("task_start")

    # 1. Query all active tenants from public schema
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.status == TenantStatus.active),
        )
        tenants = result.scalars().all()

    tenants_checked = len(tenants)
    tenants_enqueued = 0

    # 2. For each tenant, check if they have a scheduled SyncConfig
    for t in tenants:
        try:
            tenant = await TenantResolver.from_slug(t.slug)
            async with tenant.db_session() as session:
                result = await session.execute(
                    select(SyncConfig)
                    .where(
                        SyncConfig.is_active.is_(True),
                        SyncConfig.schedule_cron.isnot(None),
                    )
                    .limit(1),
                )
                config = result.scalar_one_or_none()

            if config:
                await ctx["redis"].enqueue_job(
                    "task_watch_import_folder",
                    t.slug,
                    _queue_name=DOSSIER_IMPORT_QUEUE,
                )
                tenants_enqueued += 1
                log.debug("tenant_enqueued", tenant=t.slug)

        except Exception as exc:
            log.warning(
                "tenant_scheduled_import_failed",
                tenant=t.slug,
                error=str(exc),
            )
            # Continue with next tenant

    log.info(
        "scheduled_import_complete",
        tenants_checked=tenants_checked,
        tenants_enqueued=tenants_enqueued,
    )
    return {
        "status": "ok",
        "tenants_checked": tenants_checked,
        "tenants_enqueued": tenants_enqueued,
    }


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.import_dossier.WorkerSettings`
# ---------------------------------------------------------------------------


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app config."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


async def poll_durable_imports(ctx: dict) -> str:
    """Poll PostgreSQL directly; Redis schedules the poll but is not the source of truth."""
    from sqlalchemy import func, or_

    from app.core.database import get_session_factory
    from app.core.tenant import TenantResolver
    from app.models.dossier_import_request import DossierImportRequest
    from app.models.tenant import Tenant
    from app.services.dossier.import_execution import process_one_durable_import

    if not get_settings().dossier_durable_imports_enabled:
        return "disabled"
    async with get_session_factory()() as session:
        slug = (
            await session.execute(
                select(Tenant.slug)
                .join(DossierImportRequest, DossierImportRequest.tenant_id == Tenant.id)
                .where(
                    Tenant.status == TenantStatus.active,
                    or_(
                        DossierImportRequest.state == "pending",
                        (DossierImportRequest.state == "processing")
                        & (DossierImportRequest.lease_until <= func.clock_timestamp()),
                    ),
                )
                .order_by(DossierImportRequest.created_at, DossierImportRequest.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if slug is None:
        return "empty"
    tenant = await TenantResolver.from_slug(slug)
    return await process_one_durable_import(tenant)


class WorkerSettings:
    """ARQ worker configuration for dossier import."""

    functions = [task_import_dossier, task_watch_import_folder]
    queue_name = DOSSIER_IMPORT_QUEUE
    health_check_key = (
        DOSSIER_IMPORT_QUEUE + ":durable:health-check"
        if get_settings().dossier_durable_imports_enabled
        else DOSSIER_IMPORT_QUEUE + ":health-check"
    )
    cron_jobs = [
        cron(task_scheduled_import_all, hour=6, minute=0),  # Daily 06:00 UTC
        cron(poll_durable_imports, second={0, 10, 20, 30, 40, 50}, timeout=720, max_tries=1),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 3  # Conservative: imports are I/O heavy
    job_timeout = 600  # 10 minutes
    job_completion_wait = 720
    health_check_interval = 15
    max_tries = 3
