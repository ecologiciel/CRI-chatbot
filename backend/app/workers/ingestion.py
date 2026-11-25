"""ARQ worker for KB document ingestion.

Runs as a separate process: arq app.workers.ingestion.WorkerSettings

Tasks:
    ingest_document_task  — full pipeline: download → extract → chunk → embed → index
    reindex_document_task — delete existing chunks then re-ingest
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime, timedelta

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.models.enums import KBDocumentStatus
from app.models.kb import KBDocument
from app.services.rag.extractors import extract_document

logger = structlog.get_logger()


async def _mark_document_error(tenant_slug: str, doc_uuid: uuid.UUID) -> None:
    """Record an operational failure without persisting provider secrets or content."""
    from app.core.tenant import TenantResolver

    try:
        tenant = await TenantResolver.from_slug(tenant_slug)
        async with tenant.db_session() as session:
            result = await session.execute(
                select(KBDocument).where(KBDocument.id == doc_uuid).with_for_update()
            )
            document = result.scalar_one_or_none()
            if document and document.status not in {
                KBDocumentStatus.error,
                KBDocumentStatus.rejected,
                KBDocumentStatus.expired,
                KBDocumentStatus.pending_validation,
            }:
                document.status = KBDocumentStatus.error
                document.error_message = (
                    "Le traitement a échoué. Consultez les journaux du service."
                )
    except Exception:
        logger.warning("failed_to_set_error_status", tenant=tenant_slug, document_id=str(doc_uuid))


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.minio import init_minio
    from app.core.qdrant import init_qdrant
    from app.core.redis import init_redis
    from app.services.crypto.startup_guard import verify_kms_on_startup

    setup_logging()
    get_engine()
    await verify_kms_on_startup()
    await init_redis()
    await init_qdrant()
    init_minio()
    logger.info("worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.qdrant import close_qdrant
    from app.core.redis import close_redis

    await close_qdrant()
    await close_redis()
    await close_engine()
    logger.info("worker_stopped")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def ingest_document_task(
    ctx: dict,
    tenant_slug: str,
    document_id: str,
) -> dict:
    """Download file from MinIO, extract text, run ingestion pipeline.

    Args:
        ctx: ARQ context (contains redis pool).
        tenant_slug: Tenant slug for resolution.
        document_id: UUID string of the KBDocument.

    Returns:
        dict with status, chunk_count, duration_s.
    """
    from app.core.minio import get_object_bytes
    from app.core.tenant import TenantResolver
    from app.services.rag.ingestion import get_ingestion_service

    start = time.monotonic()
    doc_uuid = uuid.UUID(document_id)
    log = logger.bind(task="ingest", tenant=tenant_slug, document_id=document_id)

    try:
        # 1. Resolve tenant
        tenant = await TenantResolver.from_slug(tenant_slug)

        # 2. Fetch document record
        async with tenant.db_session() as session:
            result = await session.execute(select(KBDocument).where(KBDocument.id == doc_uuid))
            doc = result.scalar_one_or_none()

        if doc is None:
            log.warning("document_not_found")
            return {"status": "not_found"}

        if not doc.file_path:
            log.warning("document_has_no_file")
            return {"status": "no_file"}

        # 3. Download from MinIO
        file_bytes = await get_object_bytes(tenant.minio_bucket, doc.file_path)

        # 4. Extract text
        filename = doc.file_path.rsplit("/", 1)[-1] if "/" in doc.file_path else doc.file_path
        extracted = extract_document(file_bytes, filename)

        # 5. Run ingestion pipeline
        service = get_ingestion_service()
        chunk_count = await service.ingest_document(
            tenant, doc_uuid, extracted.text, doc.title, pages=extracted.pages
        )

        duration = round(time.monotonic() - start, 1)
        log.info("ingestion_complete", chunk_count=chunk_count, duration_s=duration)
        return {"status": "ok", "chunk_count": chunk_count, "duration_s": duration}

    except Exception as exc:
        duration = round(time.monotonic() - start, 1)
        log.error("ingestion_failed", error=str(exc), duration_s=duration)

        await _mark_document_error(tenant_slug, doc_uuid)

        raise


async def reindex_document_task(
    ctx: dict,
    tenant_slug: str,
    document_id: str,
) -> dict:
    """Delete existing chunks and re-ingest a document.

    Args:
        ctx: ARQ context.
        tenant_slug: Tenant slug.
        document_id: UUID string of the KBDocument.

    Returns:
        dict with status, chunk_count, duration_s.
    """
    from app.core.minio import get_object_bytes
    from app.core.tenant import TenantResolver
    from app.services.rag.ingestion import get_ingestion_service

    start = time.monotonic()
    doc_uuid = uuid.UUID(document_id)
    log = logger.bind(task="reindex", tenant=tenant_slug, document_id=document_id)

    try:
        tenant = await TenantResolver.from_slug(tenant_slug)

        # Fetch document
        async with tenant.db_session() as session:
            result = await session.execute(select(KBDocument).where(KBDocument.id == doc_uuid))
            doc = result.scalar_one_or_none()

        if doc is None:
            log.warning("document_not_found")
            return {"status": "not_found"}

        if not doc.file_path:
            log.warning("document_has_no_file")
            return {"status": "no_file"}

        # Download from MinIO
        file_bytes = await get_object_bytes(tenant.minio_bucket, doc.file_path)

        # Extract text
        filename = doc.file_path.rsplit("/", 1)[-1] if "/" in doc.file_path else doc.file_path
        extracted = extract_document(file_bytes, filename)

        # Reindex (delete old chunks + re-ingest)
        service = get_ingestion_service()
        chunk_count = await service.reindex_document(
            tenant, doc_uuid, extracted.text, doc.title, pages=extracted.pages
        )

        duration = round(time.monotonic() - start, 1)
        log.info("reindex_complete", chunk_count=chunk_count, duration_s=duration)
        return {"status": "ok", "chunk_count": chunk_count, "duration_s": duration}

    except Exception as exc:
        duration = round(time.monotonic() - start, 1)
        log.error("reindex_failed", error=str(exc), duration_s=duration)
        await _mark_document_error(tenant_slug, doc_uuid)
        raise


async def _recover_tenant_documents(ctx: dict, tenant, cutoff: datetime) -> int:
    """Requeue stale approved work with a stable ID for each observed state."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(KBDocument.id, KBDocument.updated_at)
            .where(
                KBDocument.status.in_([KBDocumentStatus.pending, KBDocumentStatus.indexing]),
                KBDocument.updated_at < cutoff,
                KBDocument.validated_at.is_not(None),
                KBDocument.validated_by.is_not(None),
                KBDocument.file_path.is_not(None),
                or_(KBDocument.expires_at.is_(None), KBDocument.expires_at >= date.today()),
            )
            .order_by(KBDocument.updated_at)
            .limit(100)
        )
        candidates = result.all()
    queued = 0
    for document_id, updated_at in candidates:
        stamp = int(updated_at.timestamp() * 1_000_000)
        job = await ctx["redis"].enqueue_job(
            "ingest_document_task",
            tenant.slug,
            str(document_id),
            _job_id=f"kb-recovery:{tenant.slug}:{document_id}:{stamp}",
        )
        queued += int(job is not None)
    return queued


async def recover_stale_ingestions(ctx: dict) -> int:
    """Reconcile abandoned jobs across active tenants, without touching live jobs."""
    from app.core.database import get_session_factory
    from app.core.tenant import TenantResolver
    from app.models.enums import TenantStatus
    from app.models.tenant import Tenant

    async with get_session_factory()() as session:
        result = await session.execute(
            select(Tenant.slug).where(Tenant.status == TenantStatus.active)
        )
        slugs = result.scalars().all()
    cutoff = datetime.now(UTC) - timedelta(minutes=30)
    queued = 0
    for slug in slugs:
        try:
            tenant = await TenantResolver.from_slug(slug)
            queued += await _recover_tenant_documents(ctx, tenant, cutoff)
        except Exception as exc:
            logger.warning(
                "ingestion_recovery_tenant_failed", tenant=slug, error_type=type(exc).__name__
            )
    logger.info("ingestion_recovery_complete", queued=queued)
    return queued


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.ingestion.WorkerSettings`
# ---------------------------------------------------------------------------


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app config."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [ingest_document_task, reindex_document_task]
    cron_jobs = [cron(recover_stale_ingestions, minute={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 5
    job_timeout = 600  # 10 minutes
    max_tries = 3
