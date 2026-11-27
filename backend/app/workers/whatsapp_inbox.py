"""Staged dedicated ARQ worker for durable WhatsApp inboxes.

Not enabled in production. Uses a separate Redis queue so document workers
cannot accidentally consume jobs they do not implement.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import structlog
from arq import cron

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.inbox_execution import execute_claim
from app.services.whatsapp.inbox_leases import claim_next, quarantine_expired
from app.services.whatsapp.status_batch import run_status_batch
from app.services.whatsapp.worker_presence import presence_loop
from app.workers.ingestion import _get_redis_settings
from app.workers.ingestion import shutdown as infrastructure_shutdown
from app.workers.ingestion import startup as infrastructure_startup

logger = structlog.get_logger()


async def startup(ctx: dict) -> None:
    await infrastructure_startup(ctx)
    ctx["wa_presence_task"] = asyncio.create_task(presence_loop())


async def shutdown(ctx: dict) -> None:
    task = ctx.pop("wa_presence_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    # The shared signal expires naturally: deleting it could hide another worker.
    await infrastructure_shutdown(ctx)


async def poll_incoming(ctx: dict) -> str:
    """Claim at most one message; an ambiguous send is never retried here."""
    claim = await claim_next(lease_seconds=120)
    if claim is None:
        return "empty"
    finalized = await execute_claim(claim, lease_seconds=120, timeout_seconds=300)
    return "finalized" if finalized else "lease_lost"


async def recover_expired(ctx: dict) -> int:
    """Move abandoned claims to review rather than resending them."""
    count = await quarantine_expired(limit=100)
    if count:
        logger.warning("wa_inbox_claims_quarantined", count=count)
    return count


async def poll_statuses(ctx: dict) -> dict[str, int]:
    cipher = VersionedEnvelopeService(get_session_factory(), get_settings().kms_master_key)
    return await run_status_batch(cipher=cipher, limit=50)


class WorkerSettings:
    """Separate queue and conservative shutdown for in-flight provider calls."""

    functions: list = []
    cron_jobs = [
        cron(poll_incoming, second={0, 10, 20, 30, 40, 50}),
        cron(poll_statuses, second={5, 25, 45}),
        cron(recover_expired, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]
    queue_name = "arq:whatsapp-inbox"
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 3
    job_timeout = 360
    job_completion_wait = 390
    max_tries = 1
