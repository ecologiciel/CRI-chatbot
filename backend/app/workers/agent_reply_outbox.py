"""Disabled-by-default worker for the staged agent reply outbox.

Do not enable until the API, review workflow, cutover and backup integration
have been validated. A provider attempt is never retried automatically.
"""

from __future__ import annotations

from time import monotonic

import structlog
from arq import cron
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation.reply_execution import (
    AgentReplyPreconditionError,
    execute_agent_reply,
)
from app.services.escalation.reply_leases import (
    AgentReplyLeaseLostError,
    claim_next_reply,
    finish_reply,
    quarantine_expired_replies,
)
from app.services.whatsapp.sender import WhatsAppSenderService
from app.workers.notification import _get_redis_settings, shutdown, startup

logger = structlog.get_logger()


async def process_one_reply(ctx: dict) -> str:
    """Commit one claim before attempting the provider exactly once."""
    settings = get_settings()
    if not settings.agent_reply_outbox_enabled:
        return "disabled"
    factory = get_session_factory()
    async with factory() as session:
        claim = await claim_next_reply(session, lease_seconds=120)
        await session.commit()
    if claim is None:
        return "empty"
    cipher = VersionedEnvelopeService(factory, settings.kms_master_key)
    try:
        return await execute_agent_reply(claim, cipher=cipher, sender=WhatsAppSenderService())
    except Exception as exc:
        logger.warning("agent_reply_execution_failed", event_id=str(claim.id), error_type=type(exc).__name__)
        try:
            async with factory() as session:
                await finish_reply(session, claim, provider_message_id=None,
                                   precondition_failed=isinstance(exc, AgentReplyPreconditionError))
                slug = (await session.execute(select(Tenant.slug).where(Tenant.id == claim.tenant_id))).scalar_one()
                session.add(AuditLog(
                    tenant_slug=slug, user_type="system", action="agent_reply_review",
                    resource_type="agent_reply", resource_id=str(claim.id),
                    details={"reason": "precondition_changed" if isinstance(exc, AgentReplyPreconditionError) else "provider_unconfirmed"},
                ))
                await session.commit()
            return "uncertain"
        except AgentReplyLeaseLostError:
            return "lease_lost"
        except Exception as mark_exc:
            logger.error("agent_reply_quarantine_failed", event_id=str(claim.id), error_type=type(mark_exc).__name__)
            return "await_reaper"


async def drain_replies(ctx: dict) -> dict[str, int]:
    """Bound each poll; one slow provider call may exceed the soft budget."""
    started = monotonic()
    outcomes: dict[str, int] = {}
    for index in range(10):
        if index and monotonic() - started >= 30:
            break
        outcome = await process_one_reply(ctx)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome in {"empty", "disabled"}:
            break
    return outcomes


async def recover_expired_replies(ctx: dict) -> int:
    """Quarantine abandoned work even if new intake has been disabled."""
    async with get_session_factory()() as session:
        count = await quarantine_expired_replies(session, limit=100)
        await session.commit()
    if count:
        logger.warning("agent_reply_claims_quarantined", count=count)
    return count


class WorkerSettings:
    functions: list = []
    cron_jobs = [
        cron(drain_replies, second={0, 10, 20, 30, 40, 50}),
        cron(recover_expired_replies, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]
    queue_name = "arq:agent-reply-outbox"
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 1
    job_timeout = 120
    job_completion_wait = 75
    max_tries = 1
