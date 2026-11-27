"""Staged worker for the transactional dossier outbox.

Disabled by default. Cutover also requires a controlled stop of legacy import
and notification workers; an empty Redis list alone cannot prove no send is
still in flight. Do not enable this worker without the documented cutover.
"""

from __future__ import annotations

import structlog
from arq import cron
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.core.tenant import TenantResolver
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.services.notification.outbox_execution import process_one_notification
from app.services.notification.service import get_notification_service
from app.workers.notification import _get_redis_settings, shutdown, startup

logger = structlog.get_logger()


async def process_tenant_outbox(tenant_slug: str) -> str:
    """Try at most one event; refuse work when a legacy queue remains."""
    if not get_settings().dossier_notification_outbox_enabled:
        return "disabled"
    tenant = await TenantResolver.from_slug(tenant_slug)
    # Failure to query Redis propagates: unknown cutover state is not safe.
    if await get_redis().llen(f"{tenant.slug}:notification:dossier_changes"):
        logger.warning("notification_outbox_legacy_queue_present", tenant=tenant.slug)
        return "legacy_queue_present"
    return await process_one_notification(tenant, get_notification_service())


async def poll_outboxes(ctx: dict) -> dict[str, int]:
    """Poll each active institution, isolating failures between institutions."""
    if not get_settings().dossier_notification_outbox_enabled:
        return {"disabled": 1}
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Tenant.slug).where(Tenant.status == TenantStatus.active)
        )
        slugs = list(result.scalars())
    stats: dict[str, int] = {}
    for slug in slugs:
        try:
            outcome = await process_tenant_outbox(slug)
        except Exception as exc:
            logger.error(
                "notification_outbox_tenant_failed", tenant=slug, error_type=type(exc).__name__
            )
            outcome = "error"
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


class WorkerSettings:
    """Independent queue; no automatic ARQ retry after an interrupted send."""

    functions: list = []
    cron_jobs = [cron(poll_outboxes, minute=set(range(60)))]
    queue_name = "arq:dossier-notification-outbox"
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 1
    job_timeout = 3600
    job_completion_wait = 120
    max_tries = 1
