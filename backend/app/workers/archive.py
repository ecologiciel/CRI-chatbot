"""ARQ worker for weekly audit log archival to MinIO.

Runs as a separate process: arq app.workers.archive.WorkerSettings

Cron task:
    archive_audit_logs — Sunday 02:00 UTC: export previous week's audit_logs
    as gzip-compressed JSON to MinIO with SHA-256 integrity hash.

Bucket: cri-system-archive
File:   audit_logs_{YYYY}_{WW}.json.gz
Meta:   x-amz-meta-sha256  = hex digest of uncompressed JSON
        x-amz-meta-period  = start_date / end_date

Retention: 24 months on MinIO (manual policy in production).
Does NOT delete logs from PostgreSQL — purge is a separate job.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import select, text

from app.core.config import get_settings

logger = structlog.get_logger()

_ARCHIVE_BUCKET = "cri-system-archive"


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the archive worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.minio import init_minio
    from app.core.redis import init_redis

    setup_logging()
    get_engine()
    await init_redis()
    init_minio()
    logger.info("archive_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.redis import close_redis

    await close_redis()
    await close_engine()
    logger.info("archive_worker_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_default(obj: object) -> str:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def _ensure_bucket(minio, bucket_name: str) -> None:  # noqa: ANN001
    """Create the archive bucket if it does not exist."""
    if not await minio.bucket_exists(bucket_name):
        await minio.make_bucket(bucket_name)
        logger.info("bucket_created", bucket=bucket_name)


def _previous_week_boundaries() -> tuple[datetime, datetime]:
    """Return (monday_00:00, sunday_23:59:59) of the previous ISO week."""
    now = datetime.now(timezone.utc)
    # Monday of the current week
    current_monday = now - timedelta(days=now.weekday())
    current_monday = current_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    # Previous week
    prev_monday = current_monday - timedelta(weeks=1)
    prev_sunday = prev_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return prev_monday, prev_sunday


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


async def archive_audit_logs(ctx: dict) -> dict:
    """Export previous week's audit logs to MinIO as signed gzip JSON.

    Args:
        ctx: ARQ context (contains redis pool).

    Returns:
        Dict with status, object_name, row_count, sha256, compressed/uncompressed sizes.
    """
    from app.core.database import get_session_factory
    from app.core.minio import get_minio
    from app.models.audit import AuditLog

    start_date, end_date = _previous_week_boundaries()
    iso_cal = start_date.isocalendar()
    year, week = iso_cal[0], iso_cal[1]

    log = logger.bind(
        task="archive_audit_logs",
        year=year,
        week=week,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    log.info("archive_start")

    # 1. Query audit_logs for the period
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.created_at >= start_date)
            .where(AuditLog.created_at <= end_date)
            .order_by(AuditLog.created_at.asc())
        )
        rows = result.scalars().all()

    # 2. Convert ORM objects to dicts
    columns = AuditLog.__table__.columns
    records = [
        {col.name: getattr(row, col.name) for col in columns}
        for row in rows
    ]

    # 3. Serialize to JSON
    json_str = json.dumps(records, default=_json_default, ensure_ascii=False)
    json_bytes = json_str.encode("utf-8")

    # 4. SHA-256 of uncompressed JSON
    sha256_hash = hashlib.sha256(json_bytes).hexdigest()

    # 5. Gzip compress
    compressed = gzip.compress(json_bytes)

    # 6. Upload to MinIO
    minio = get_minio()
    await _ensure_bucket(minio, _ARCHIVE_BUCKET)

    object_name = f"audit_logs_{year}_{week:02d}.json.gz"
    data = io.BytesIO(compressed)

    await minio.put_object(
        _ARCHIVE_BUCKET,
        object_name,
        data,
        length=len(compressed),
        content_type="application/gzip",
        metadata={
            "x-amz-meta-sha256": sha256_hash,
            "x-amz-meta-period": f"{start_date.isoformat()}/{end_date.isoformat()}",
        },
    )

    stats = {
        "status": "ok",
        "object_name": object_name,
        "row_count": len(records),
        "uncompressed_bytes": len(json_bytes),
        "compressed_bytes": len(compressed),
        "sha256": sha256_hash,
    }
    log.info("archive_complete", **stats)
    return stats


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.archive.WorkerSettings`
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
    """ARQ worker configuration for audit log archival."""

    functions: list = []
    cron_jobs = [
        cron(archive_audit_logs, weekday=6, hour=2, minute=0),  # Sunday 02:00 UTC
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 1
    job_timeout = 300  # 5 minutes
