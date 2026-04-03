"""ARQ worker for CNDP-compliant data purge (loi 09-08, Art. 3).

Runs as a separate process: arq app.workers.purge.WorkerSettings

Cron:
    task_purge_expired_data — daily 03:00 UTC: delete expired conversations
    across all active tenants.

Retention policy:
    conversations: 90 days after ended_at (CNDP Art. 3)
    messages/feedback: cascade-deleted with conversations (FK CASCADE)
    escalations: cascade-deleted with conversations (FK CASCADE)

Only conversations with ended_at IS NOT NULL AND ended_at < cutoff are purged.
Active, escalated, or human_handled conversations are NEVER deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import delete, select, text

from app.core.config import get_settings

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETENTION_DAYS_CONVERSATIONS: int = 90
"""Default retention period for ended conversations (CNDP loi 09-08)."""

BATCH_SIZE: int = 1000
"""Max conversations deleted per batch to avoid long-held DB locks."""


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the purge worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.redis import init_redis

    setup_logging()
    get_engine()
    await init_redis()
    logger.info("purge_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.redis import close_redis

    await close_redis()
    await close_engine()
    logger.info("purge_worker_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app config."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


async def _purge_tenant_conversations(
    slug: str,
    cutoff: datetime,
) -> dict[str, int]:
    """Delete expired conversations for a single tenant.

    Conversations are deleted in batches of ``BATCH_SIZE``.  Messages,
    feedback, and escalations are cascade-deleted by PostgreSQL FK rules.

    Args:
        slug: Tenant slug identifier.
        cutoff: Delete conversations with ``ended_at < cutoff``.

    Returns:
        Dict with ``conversations_deleted`` count.
    """
    from app.core.tenant import TenantResolver
    from app.models.conversation import Conversation

    log = logger.bind(task="purge_conversations", tenant=slug)

    tenant = await TenantResolver.from_slug(slug)
    total_deleted = 0

    async with tenant.db_session() as session:
        while True:
            # PostgreSQL doesn't support DELETE ... LIMIT, so use subquery.
            subq = (
                select(Conversation.id)
                .where(Conversation.ended_at.is_not(None))
                .where(Conversation.ended_at < cutoff)
                .limit(BATCH_SIZE)
            )
            stmt = (
                delete(Conversation)
                .where(Conversation.id.in_(subq))
            )
            result = await session.execute(stmt)
            batch_deleted = result.rowcount

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            await session.commit()
            log.info(
                "purge_batch",
                batch_deleted=batch_deleted,
                total_deleted=total_deleted,
            )

    # Audit trail (only if something was actually deleted)
    if total_deleted > 0:
        from app.schemas.audit import AuditLogCreate
        from app.services.audit.service import get_audit_service

        audit = get_audit_service()
        await audit.log_action(
            AuditLogCreate(
                tenant_slug=slug,
                user_id=None,
                user_type="system",
                action="delete",
                resource_type="conversation",
                resource_id=None,
                details={
                    "reason": "cndp_retention_policy",
                    "retention_days": RETENTION_DAYS_CONVERSATIONS,
                    "cutoff_date": cutoff.isoformat(),
                    "conversations_deleted": total_deleted,
                },
            )
        )

    log.info("purge_tenant_complete", conversations_deleted=total_deleted)
    return {"conversations_deleted": total_deleted}


# ---------------------------------------------------------------------------
# Main cron task
# ---------------------------------------------------------------------------


async def task_purge_expired_data(ctx: dict) -> dict[str, Any]:
    """Purge expired data for all active tenants (CNDP compliance).

    Called by ARQ cron daily at 03:00 UTC.

    Args:
        ctx: ARQ context (contains redis pool).

    Returns:
        Aggregate stats dict with tenant counts and total purged.
    """
    from app.core.database import get_session_factory
    from app.models.enums import TenantStatus
    from app.models.tenant import Tenant

    log = logger.bind(task="purge_expired_data")
    log.info("task_start")

    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS_CONVERSATIONS)

    # 1. Query active tenant slugs from public schema
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(
            select(Tenant.slug).where(Tenant.status == TenantStatus.active.value),
        )
        slugs: list[str] = [row[0] for row in result.all()]

    log.info("tenants_found", count=len(slugs))

    # 2. Purge each tenant
    total_deleted = 0
    tenants_with_purges = 0
    tenants_errored = 0

    for slug in slugs:
        try:
            stats = await _purge_tenant_conversations(slug, cutoff)
            deleted = stats["conversations_deleted"]
            total_deleted += deleted
            if deleted > 0:
                tenants_with_purges += 1
        except Exception:
            tenants_errored += 1
            log.error("purge_tenant_failed", tenant=slug, exc_info=True)

    # 3. Summary
    summary = {
        "tenants_processed": len(slugs),
        "tenants_with_purges": tenants_with_purges,
        "tenants_errored": tenants_errored,
        "total_conversations_deleted": total_deleted,
        "cutoff_date": cutoff.isoformat(),
        "retention_days": RETENTION_DAYS_CONVERSATIONS,
    }
    log.info("task_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.purge.WorkerSettings`
# ---------------------------------------------------------------------------


class WorkerSettings:
    """ARQ worker configuration for CNDP data purge."""

    functions: list = []
    cron_jobs = [
        cron(task_purge_expired_data, hour=3, minute=0),  # Daily 03:00 UTC
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 1
    job_timeout = 600  # 10 minutes (multi-tenant purge)
