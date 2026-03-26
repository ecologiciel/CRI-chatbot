"""ARQ worker for KB document ingestion.

Runs as a separate process: arq app.workers.ingestion.WorkerSettings

Tasks:
    ingest_document_task  — full pipeline: download → extract → chunk → embed → index
    reindex_document_task — delete existing chunks then re-ingest
"""

from __future__ import annotations

import io
import time
import uuid

import structlog
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import IngestionError
from app.models.enums import KBDocumentStatus
from app.models.kb import KBDocument
from app.services.rag.extractors import extract_text

logger = structlog.get_logger()


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

    setup_logging()
    get_engine()
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
    from app.core.minio import get_minio
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
            result = await session.execute(
                select(KBDocument).where(KBDocument.id == doc_uuid)
            )
            doc = result.scalar_one_or_none()

        if doc is None:
            log.warning("document_not_found")
            return {"status": "not_found"}

        if not doc.file_path:
            log.warning("document_has_no_file")
            return {"status": "no_file"}

        # 3. Download from MinIO
        minio = get_minio()
        response = await minio.get_object(tenant.minio_bucket, doc.file_path)
        file_bytes = await response.read()
        response.close()
        await response.release()

        # 4. Extract text
        filename = doc.file_path.rsplit("/", 1)[-1] if "/" in doc.file_path else doc.file_path
        content = extract_text(file_bytes, filename)

        # 5. Run ingestion pipeline
        service = get_ingestion_service()
        chunk_count = await service.ingest_document(tenant, doc_uuid, content, doc.title)

        duration = round(time.monotonic() - start, 1)
        log.info("ingestion_complete", chunk_count=chunk_count, duration_s=duration)
        return {"status": "ok", "chunk_count": chunk_count, "duration_s": duration}

    except Exception as exc:
        duration = round(time.monotonic() - start, 1)
        log.error("ingestion_failed", error=str(exc), duration_s=duration)

        # Best-effort: mark document as error if IngestionService didn't already
        try:
            from app.core.tenant import TenantResolver as TR

            t = await TR.from_slug(tenant_slug)
            async with t.db_session() as session:
                result = await session.execute(
                    select(KBDocument).where(KBDocument.id == doc_uuid)
                )
                d = result.scalar_one_or_none()
                if d and d.status != KBDocumentStatus.error:
                    d.status = KBDocumentStatus.error
                    d.error_message = str(exc)[:500]
        except Exception:
            log.warning("failed_to_set_error_status")

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
    from app.core.minio import get_minio
    from app.core.tenant import TenantResolver
    from app.services.rag.ingestion import get_ingestion_service

    start = time.monotonic()
    doc_uuid = uuid.UUID(document_id)
    log = logger.bind(task="reindex", tenant=tenant_slug, document_id=document_id)

    try:
        tenant = await TenantResolver.from_slug(tenant_slug)

        # Fetch document
        async with tenant.db_session() as session:
            result = await session.execute(
                select(KBDocument).where(KBDocument.id == doc_uuid)
            )
            doc = result.scalar_one_or_none()

        if doc is None:
            log.warning("document_not_found")
            return {"status": "not_found"}

        if not doc.file_path:
            log.warning("document_has_no_file")
            return {"status": "no_file"}

        # Download from MinIO
        minio = get_minio()
        response = await minio.get_object(tenant.minio_bucket, doc.file_path)
        file_bytes = await response.read()
        response.close()
        await response.release()

        # Extract text
        filename = doc.file_path.rsplit("/", 1)[-1] if "/" in doc.file_path else doc.file_path
        content = extract_text(file_bytes, filename)

        # Reindex (delete old chunks + re-ingest)
        service = get_ingestion_service()
        chunk_count = await service.reindex_document(tenant, doc_uuid, content, doc.title)

        duration = round(time.monotonic() - start, 1)
        log.info("reindex_complete", chunk_count=chunk_count, duration_s=duration)
        return {"status": "ok", "chunk_count": chunk_count, "duration_s": duration}

    except Exception as exc:
        duration = round(time.monotonic() - start, 1)
        log.error("reindex_failed", error=str(exc), duration_s=duration)
        raise


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
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 5
    job_timeout = 600  # 10 minutes
    max_tries = 3
