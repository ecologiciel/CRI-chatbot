"""ARQ worker for CNDP-compliant data purge (loi 09-08, Art. 3).

Runs as a separate process: arq app.workers.purge.WorkerSettings

Cron:
    task_purge_expired_data — daily 03:00 UTC: delete expired conversations
    across all active tenants.

Retention policy:
    conversations: 90 days after ended_at (CNDP Art. 3)
    messages/feedback: cascade-deleted with conversations (FK CASCADE)
    escalations: cascade-deleted with conversations (FK CASCADE)

Ended conversations follow the configured retention period. Unclosed anonymous
web conversations also expire after inactivity, including on non-demo tenants.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import and_, case, delete, func, or_, select, text

from app.core.config import get_settings
from app.services.dossier.import_retention import purge_import_sources
from app.services.escalation.reply_retention import redact_expired_agent_replies
from app.services.notification.outbox_retention import redact_expired_outbox
from app.services.whatsapp.inbox_retention import redact_expired_inbox

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
    from app.services.crypto.startup_guard import verify_kms_on_startup

    setup_logging()
    get_engine()
    await verify_kms_on_startup()
    await init_redis()
    settings = get_settings()
    if (
        settings.dossier_durable_imports_enabled is True
        and settings.dossier_import_retention_days > 0
    ):
        from app.core.minio import init_minio

        init_minio()
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
    *,
    purge_active: bool = False,
    retention_days: int = RETENTION_DAYS_CONVERSATIONS,
) -> dict[str, int]:
    """Delete expired conversations for a single tenant.

    Conversations are deleted in batches of ``BATCH_SIZE``.  Messages,
    feedback, and escalations are cascade-deleted by PostgreSQL FK rules.

    Args:
        slug: Tenant slug identifier.
        cutoff: Delete expired conversations before this timestamp.

    Returns:
        Dict with ``conversations_deleted`` count.
    """
    from app.core.tenant import TenantResolver
    from app.models.contact import Contact
    from app.models.conversation import Conversation, Message
    from app.models.enums import ContactSource

    log = logger.bind(task="purge_conversations", tenant=slug)

    tenant = await TenantResolver.from_slug(slug)
    total_deleted = 0

    # A contact may have arbitrary user-supplied metadata. Casting a JSON
    # string or object directly to boolean can abort the whole tenant purge.
    # Only the literal JSON boolean true identifies a pseudonymous contact.
    pseudonymous_web = case(
        (
            func.jsonb_typeof(Contact.metadata_["pseudonymous"]) == "boolean",
            Contact.metadata_["pseudonymous"].as_boolean().is_(True),
        ),
        else_=False,
    )

    async with tenant.db_session() as session:
        while True:
            # PostgreSQL doesn't support DELETE ... LIMIT, so use subquery.
            subq = select(Conversation.id).limit(BATCH_SIZE)
            # A web conversation may never be explicitly closed. Use recent
            # message creation time to avoid purging an old but active session.
            recent_message = (
                select(Message.id)
                .where(
                    Message.conversation_id == Conversation.id,
                    Message.created_at >= cutoff,
                )
                .exists()
            )
            web_contact = (
                select(Contact.id)
                .where(
                    Contact.id == Conversation.contact_id,
                    Contact.source == ContactSource.web,
                    pseudonymous_web,
                )
                .exists()
            )
            unclosed_expired = and_(
                Conversation.ended_at.is_(None),
                Conversation.started_at < cutoff,
                ~recent_message,
            )
            if not purge_active:
                unclosed_expired = and_(unclosed_expired, web_contact)
            subq = subq.where(or_(Conversation.ended_at < cutoff, unclosed_expired))
            stmt = delete(Conversation).where(Conversation.id.in_(subq))
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

        # A web demo contact is pseudonymous and exists solely to group a
        # Restrict cleanup to old web contacts, never ordinary CRM contacts or
        # a newly created session that has yet to create its first conversation.
        orphaned_web_contacts = (
            delete(Contact)
            .where(
                Contact.source == ContactSource.web,
                pseudonymous_web,
                Contact.created_at < cutoff,
            )
            .where(~select(Conversation.id).where(Conversation.contact_id == Contact.id).exists())
        )
        await session.execute(orphaned_web_contacts)
        await session.commit()

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
                    "retention_days": retention_days,
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

    # 1. Query active tenant slugs from public schema
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET LOCAL search_path TO public"))
        result = await session.execute(
            select(
                Tenant.slug,
                Tenant.is_demo,
                Tenant.conversation_retention_days,
            ).where(Tenant.status == TenantStatus.active.value),
        )
        tenants = list(result.all())

    log.info("tenants_found", count=len(tenants))

    # 2. Purge each tenant
    total_deleted = 0
    tenants_with_purges = 0
    tenants_errored = 0

    for slug, is_demo, retention_days in tenants:
        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            stats = await _purge_tenant_conversations(
                slug,
                cutoff,
                purge_active=is_demo,
                retention_days=retention_days,
            )
            deleted = stats["conversations_deleted"]
            total_deleted += deleted
            if deleted > 0:
                tenants_with_purges += 1
        except Exception:
            tenants_errored += 1
            log.error("purge_tenant_failed", tenant=slug, exc_info=True)

    # 3. Summary
    summary = {
        "tenants_processed": len(tenants),
        "tenants_with_purges": tenants_with_purges,
        "tenants_errored": tenants_errored,
        "total_conversations_deleted": total_deleted,
        "default_retention_days": RETENTION_DAYS_CONVERSATIONS,
    }
    log.info("task_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.purge.WorkerSettings`
# ---------------------------------------------------------------------------


class WorkerSettings:
    """ARQ worker configuration for CNDP data purge."""

    # A worker consumes every job from its queue, even functions it does not
    # implement. Keep purge cron jobs away from the default ingestion queue.
    queue_name = "arq:queue:purge"
    functions: list = []
    cron_jobs = [
        cron(task_purge_expired_data, hour=3, minute=0),  # Daily 03:00 UTC
        cron(redact_expired_inbox, minute=20),  # Hourly; includes inactive tenants.
        cron(redact_expired_outbox, minute=30),  # Hourly; includes inactive tenants.
        cron(purge_import_sources, minute=40),  # Opt-in terminal import snapshots.
        cron(redact_expired_agent_replies, minute=50),  # Terminal replies only.
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 1
    job_timeout = 600  # 10 minutes (multi-tenant purge)
    job_completion_wait = 630  # Finish in-flight jobs on a graceful shutdown.
