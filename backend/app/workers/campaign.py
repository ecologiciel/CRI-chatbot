"""ARQ worker for WhatsApp campaign mass-messaging.

Runs as a separate process: arq app.workers.campaign.WorkerSettings

Tasks:
    send_campaign_task — send template messages to all pending recipients
                         with rate-limiting, pause support, and crash recovery.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings
from sqlalchemy import func, select, text, update

from app.core.config import get_settings
from app.models.campaign import Campaign, CampaignRecipient
from app.models.contact import Contact
from app.models.enums import CampaignStatus, RecipientStatus

logger = structlog.get_logger()

# ── Constants (configurable) ──

BATCH_SIZE = 50
"""Number of recipients processed per batch."""

BATCH_DELAY_SECONDS = 0.7
"""Delay between batches (~70 msg/s, under the Meta BSP max of 80 msg/s)."""

SEND_CONCURRENCY = 10
"""Max concurrent WhatsApp API calls within a batch."""


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the campaign worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.redis import init_redis

    setup_logging()
    get_engine()
    await init_redis()
    logger.info("campaign_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.redis import close_redis

    await close_redis()
    await close_engine()
    logger.info("campaign_worker_stopped")


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


async def send_campaign_task(
    ctx: dict,
    tenant_slug: str,
    campaign_id: str,
) -> dict:
    """Send WhatsApp template messages to all pending campaign recipients.

    Characteristics:
    - **Idempotent**: only processes recipients with ``status='pending'``.
    - **Crash-resistant**: on restart, picks up where it left off.
    - **Pausable**: checks a Redis flag between batches.
    - **Quota-aware**: increments the shared annual counter per sent message.

    Args:
        ctx: ARQ context dict.
        tenant_slug: Slug of the tenant owning the campaign.
        campaign_id: UUID string of the campaign.

    Returns:
        Dict with ``sent``, ``failed``, ``paused`` keys.
    """
    from app.core.redis import get_redis
    from app.core.tenant import TenantResolver
    from app.services.campaign.service import CampaignService, get_campaign_service
    from app.services.whatsapp.session import WhatsAppSessionManager

    cid = uuid.UUID(campaign_id)
    log = logger.bind(task="send_campaign", tenant=tenant_slug, campaign_id=campaign_id)

    try:
        # 1. Resolve tenant
        tenant = await TenantResolver.from_slug(tenant_slug)
    except Exception:
        log.error("tenant_resolution_failed")
        raise

    redis = get_redis()
    service = get_campaign_service()
    session_mgr = WhatsAppSessionManager()
    pause_key = f"{tenant.redis_prefix}:campaign:{campaign_id}:paused"

    # 2. Load and verify campaign
    async with tenant.db_session() as session:
        result = await session.execute(
            select(Campaign).where(Campaign.id == cid),
        )
        campaign = result.scalar_one_or_none()

    if campaign is None:
        log.error("campaign_not_found")
        return {"sent": 0, "failed": 0, "paused": False}

    # Idempotent: skip if already completed or failed
    if campaign.status in (CampaignStatus.completed, CampaignStatus.failed):
        log.info("campaign_already_finished", status=campaign.status.value)
        return {"sent": 0, "failed": 0, "paused": False}

    # 3. Reconcile stats from actual recipient statuses (crash recovery)
    await _reconcile_stats(tenant, cid)

    sent_count = 0
    failed_count = 0
    paused = False

    # 4. Main send loop
    while True:
        # Check pause flag
        is_paused = await redis.get(pause_key)
        if is_paused:
            log.info("campaign_paused_by_flag")
            async with tenant.db_session() as session:
                await session.execute(
                    update(Campaign)
                    .where(Campaign.id == cid)
                    .values(status=CampaignStatus.paused),
                )
            paused = True
            break

        # Fetch next batch of pending recipients
        async with tenant.db_session() as session:
            batch_q = (
                select(CampaignRecipient)
                .where(
                    CampaignRecipient.campaign_id == cid,
                    CampaignRecipient.status == RecipientStatus.pending,
                )
                .order_by(CampaignRecipient.id)
                .limit(BATCH_SIZE)
            )
            batch = list((await session.execute(batch_q)).scalars().all())

        if not batch:
            break  # All recipients processed

        # Send batch with concurrency control
        semaphore = asyncio.Semaphore(SEND_CONCURRENCY)
        batch_sent = 0
        batch_failed = 0

        async def _send_one(recipient: CampaignRecipient) -> bool:
            async with semaphore:
                return await _send_single_recipient(
                    tenant, campaign, recipient, service, session_mgr,
                )

        results = await asyncio.gather(
            *[_send_one(r) for r in batch],
            return_exceptions=True,
        )

        for r in results:
            if r is True:
                batch_sent += 1
            else:
                batch_failed += 1

        sent_count += batch_sent
        failed_count += batch_failed

        # Update campaign stats atomically
        await _update_stats_delta(tenant, cid, batch_sent, batch_failed)

        log.info(
            "campaign_batch_sent",
            batch_sent=batch_sent,
            batch_failed=batch_failed,
            total_sent=sent_count,
        )

        # Rate limiting between batches
        await asyncio.sleep(BATCH_DELAY_SECONDS)

    # 5. Finalise campaign
    if not paused:
        final_status = CampaignStatus.completed

        # If ALL recipients failed, mark campaign as failed
        async with tenant.db_session() as session:
            pending_count = (
                await session.execute(
                    select(func.count())
                    .select_from(CampaignRecipient)
                    .where(
                        CampaignRecipient.campaign_id == cid,
                        CampaignRecipient.status == RecipientStatus.sent,
                    ),
                )
            ).scalar_one()

            if pending_count == 0 and failed_count > 0:
                final_status = CampaignStatus.failed

        async with tenant.db_session() as session:
            await session.execute(
                update(Campaign)
                .where(Campaign.id == cid)
                .values(
                    status=final_status,
                    completed_at=datetime.now(UTC),
                ),
            )

    # 6. Clean up pause flag
    await redis.delete(pause_key)

    log.info(
        "campaign_worker_done",
        total_sent=sent_count,
        total_failed=failed_count,
        paused=paused,
    )

    return {"sent": sent_count, "failed": failed_count, "paused": paused}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_single_recipient(
    tenant: "TenantContext",
    campaign: Campaign,
    recipient: CampaignRecipient,
    service: "CampaignService",
    session_mgr: "WhatsAppSessionManager",
) -> bool:
    """Send a template message to one recipient and update their status.

    Args:
        tenant: Current tenant context.
        campaign: The Campaign ORM instance.
        recipient: The CampaignRecipient ORM instance.
        service: CampaignService for variable resolution and sender access.
        session_mgr: WhatsAppSessionManager for quota increment.

    Returns:
        True on success, False on failure.
    """
    log = logger.bind(
        recipient_id=str(recipient.id),
        campaign_id=str(campaign.id),
    )

    try:
        # Load contact
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == recipient.contact_id),
            )
            contact = result.scalar_one_or_none()

        if contact is None:
            log.warning("recipient_contact_missing", contact_id=str(recipient.contact_id))
            await _update_recipient_status(
                tenant, recipient.id, RecipientStatus.failed,
                error_message="Contact not found",
            )
            return False

        # Resolve template variables
        components = service.resolve_variables(campaign.variable_mapping, contact)

        # Send via WhatsApp
        wamid = await service._sender.send_template(
            tenant=tenant,
            to=contact.phone,
            template_name=campaign.template_name,
            language_code=campaign.template_language,
            components=components or None,
        )

        # Update recipient: sent
        await _update_recipient_status(
            tenant, recipient.id, RecipientStatus.sent,
            wamid=wamid,
        )

        # Increment shared quota counter
        await session_mgr.increment_quota(tenant)

        return True

    except Exception as exc:
        log.error("campaign_send_failed", error=str(exc))
        await _update_recipient_status(
            tenant, recipient.id, RecipientStatus.failed,
            error_message=str(exc)[:500],
        )
        return False


async def _update_recipient_status(
    tenant: "TenantContext",
    recipient_id: uuid.UUID,
    status: RecipientStatus,
    *,
    wamid: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update a single recipient's delivery status."""
    values: dict = {"status": status}
    if status == RecipientStatus.sent:
        values["whatsapp_message_id"] = wamid
        values["sent_at"] = datetime.now(UTC)
    if error_message is not None:
        values["error_message"] = error_message

    async with tenant.db_session() as session:
        await session.execute(
            update(CampaignRecipient)
            .where(CampaignRecipient.id == recipient_id)
            .values(**values),
        )


async def _update_stats_delta(
    tenant: "TenantContext",
    campaign_id: uuid.UUID,
    sent_delta: int,
    failed_delta: int,
) -> None:
    """Atomically increment campaign stats JSONB using SQL arithmetic.

    Avoids read-modify-write race conditions with concurrent webhook
    status updates (delivered/read).
    """
    async with tenant.db_session() as session:
        await session.execute(
            text("""
                UPDATE campaigns
                SET stats = jsonb_build_object(
                    'total',     (stats->>'total')::int,
                    'sent',      (stats->>'sent')::int + :sent_delta,
                    'delivered', (stats->>'delivered')::int,
                    'read',      (stats->>'read')::int,
                    'failed',    (stats->>'failed')::int + :failed_delta
                )
                WHERE id = :cid
            """),
            {"sent_delta": sent_delta, "failed_delta": failed_delta, "cid": campaign_id},
        )


async def _reconcile_stats(
    tenant: "TenantContext",
    campaign_id: uuid.UUID,
) -> None:
    """Rebuild campaign stats from actual recipient statuses.

    Called on worker startup to recover from a potential crash where
    stats JSONB was not fully updated.
    """
    async with tenant.db_session() as session:
        result = await session.execute(
            select(
                CampaignRecipient.status,
                func.count().label("cnt"),
            )
            .where(CampaignRecipient.campaign_id == campaign_id)
            .group_by(CampaignRecipient.status),
        )
        counts = {row.status: row.cnt for row in result}

    sent = counts.get(RecipientStatus.sent, 0)
    delivered = counts.get(RecipientStatus.delivered, 0)
    read = counts.get(RecipientStatus.read, 0)
    failed = counts.get(RecipientStatus.failed, 0)
    pending = counts.get(RecipientStatus.pending, 0)
    total = sent + delivered + read + failed + pending

    async with tenant.db_session() as session:
        await session.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(
                stats={
                    "total": total,
                    "sent": sent + delivered + read,  # sent includes delivered+read
                    "delivered": delivered + read,  # delivered includes read
                    "read": read,
                    "failed": failed,
                },
            ),
        )


# ---------------------------------------------------------------------------
# ARQ configuration
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
    """ARQ worker configuration for WhatsApp campaign sending."""

    functions = [send_campaign_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 3
    job_timeout = 7200  # 2 hours
    max_tries = 2
