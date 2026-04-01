"""ARQ worker for proactive WhatsApp dossier notifications.

Runs as a separate process: arq app.workers.notification.WorkerSettings

Tasks:
    task_send_notifications — process the notification queue for a single tenant.

Cron:
    process_all_notifications — every 2 min, drain all active tenants' queues.

The notification queue ``{slug}:notification:dossier_changes`` is populated by
the dossier import service when a status change is detected.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings

logger = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────────

BATCH_SIZE: int = 50
"""Max events drained per iteration from a tenant's queue."""

RETRY_DELAYS: list[int] = [10, 30, 90]
"""Backoff delays (seconds) for WhatsApp send retries."""


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the notification worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.redis import init_redis

    setup_logging()
    get_engine()
    await init_redis()
    logger.info("notification_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.redis import close_redis

    await close_redis()
    await close_engine()
    logger.info("notification_worker_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app configuration."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


async def _send_with_retry(
    service: Any,
    event: Any,
    tenant: Any,
    log: Any,
) -> dict[str, Any]:
    """Send a notification with exponential backoff retry.

    Retries up to 3 times on transient WhatsApp failures.
    """
    last_error: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        try:
            return await service.send_notification(event, tenant)
        except Exception as exc:
            last_error = exc
            log.warning(
                "notification_retry",
                attempt=attempt + 1,
                delay=delay,
                error=str(exc),
            )
            if attempt < len(RETRY_DELAYS) - 1:
                await asyncio.sleep(delay)

    # Final failure — the service already audits the failure internally
    log.error("notification_exhausted_retries", error=str(last_error))
    return {"status": "failed", "error": str(last_error)}


async def _process_tenant_notifications(tenant_slug: str) -> dict[str, int]:
    """Drain and process the notification queue for a single tenant.

    Returns:
        Stats dict with processed/sent/skipped/failed counts.
    """
    from app.core.redis import get_redis
    from app.core.tenant import TenantResolver
    from app.services.notification.service import (
        DossierChangeEvent,
        get_notification_service,
    )

    log = logger.bind(task="process_notifications", tenant=tenant_slug)

    tenant = await TenantResolver.from_slug(tenant_slug)
    redis = get_redis()
    service = get_notification_service()
    queue_key = f"{tenant.slug}:notification:dossier_changes"

    stats: dict[str, int] = {
        "processed": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 0,
    }

    while True:
        # Atomic drain: read + remove up to BATCH_SIZE items
        pipe = redis.pipeline()
        pipe.lrange(queue_key, 0, BATCH_SIZE - 1)
        pipe.ltrim(queue_key, BATCH_SIZE, -1)
        results = await pipe.execute()
        items: list[str] = results[0]

        if not items:
            break

        for raw in items:
            try:
                data = json.loads(raw)
                event = DossierChangeEvent(**data)
                result = await _send_with_retry(service, event, tenant, log)

                stats["processed"] += 1
                status = result.get("status", "unknown")
                if status == "sent":
                    stats["sent"] += 1
                elif status == "skipped":
                    stats["skipped"] += 1
                elif status == "failed":
                    stats["failed"] += 1

            except Exception as exc:
                log.error(
                    "notification_event_error",
                    error=str(exc),
                    raw_event=raw[:200],
                    exc_info=True,
                )
                stats["processed"] += 1
                stats["failed"] += 1

    if stats["processed"] > 0:
        log.info("tenant_notifications_processed", **stats)

    return stats


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def task_send_notifications(
    ctx: dict,
    tenant_slug: str,
) -> dict[str, Any]:
    """Process notification queue for a specific tenant (on-demand).

    Enqueue via: ``await pool.enqueue_job("task_send_notifications", slug)``

    Args:
        ctx: ARQ context dict.
        tenant_slug: Slug of the tenant to process.

    Returns:
        Stats dict with processed/sent/skipped/failed counts.
    """
    log = logger.bind(task="send_notifications", tenant=tenant_slug)
    try:
        return await _process_tenant_notifications(tenant_slug)
    except Exception:
        log.error("task_send_notifications_failed", exc_info=True)
        raise


async def process_all_notifications(ctx: dict) -> dict[str, Any]:
    """Cron task: drain notification queues for ALL active tenants.

    Runs every 2 minutes.  For each active tenant, reads and processes
    all pending dossier-change events from the Redis queue.

    Args:
        ctx: ARQ context dict.

    Returns:
        Aggregate stats dict.
    """
    from app.core.database import get_session_factory
    from app.models.enums import TenantStatus
    from app.models.tenant import Tenant

    from sqlalchemy import select, text

    log = logger.bind(task="process_all_notifications")

    # Query active tenant slugs from public schema
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(
            select(Tenant.slug).where(Tenant.status == TenantStatus.active.value),
        )
        slugs: list[str] = [row[0] for row in result.all()]

    aggregate: dict[str, int] = {
        "tenants_checked": len(slugs),
        "total_processed": 0,
        "total_sent": 0,
        "total_skipped": 0,
        "total_failed": 0,
    }

    for slug in slugs:
        try:
            stats = await _process_tenant_notifications(slug)
            aggregate["total_processed"] += stats["processed"]
            aggregate["total_sent"] += stats["sent"]
            aggregate["total_skipped"] += stats["skipped"]
            aggregate["total_failed"] += stats["failed"]
        except Exception as exc:
            log.error(
                "tenant_notification_error",
                tenant=slug,
                error=str(exc),
                exc_info=True,
            )

    if aggregate["total_processed"] > 0:
        log.info("all_notifications_processed", **aggregate)

    return aggregate


# ---------------------------------------------------------------------------
# ARQ Worker Settings
# ---------------------------------------------------------------------------


class WorkerSettings:
    """ARQ worker configuration for the notification worker.

    Run: ``arq app.workers.notification.WorkerSettings``
    """

    functions = [task_send_notifications]
    cron_jobs = [
        cron(process_all_notifications, minute=set(range(0, 60, 2))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 3
    job_timeout = 300  # 5 minutes
    max_tries = 2
