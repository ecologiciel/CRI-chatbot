"""Fenced execution for the staged WhatsApp inbox; not wired into production."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import structlog

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.handler import HandlingOutcome, get_message_handler
from app.services.whatsapp.inbox_channel import protect_claim_channel
from app.services.whatsapp.inbox_leases import InboxClaim, defer_claim, finish_claim, renew_claim
from app.services.whatsapp.inbox_payload import decrypt_claim
from app.services.whatsapp.outbound_fence import outbound_scope

logger = structlog.get_logger()


async def _process(claim: InboxClaim) -> HandlingOutcome:
    cipher = VersionedEnvelopeService(get_session_factory(), get_settings().kms_master_key)
    async with protect_claim_channel(claim) as tenant:
        payload = await decrypt_claim(claim, cipher)
        with outbound_scope(claim, payload.message.from_) as scope:
            outcome = await get_message_handler().handle_message(
                tenant, payload.message, payload.contacts, durable=True
            )
            return HandlingOutcome.uncertain if scope.uncertain else outcome


async def _heartbeat(claim: InboxClaim, lease_seconds: int) -> None:
    while True:
        await asyncio.sleep(lease_seconds / 3)
        if not await renew_claim(claim.id, claim.lease_token, lease_seconds=lease_seconds):
            raise RuntimeError("Inbox lease lost")


async def execute_claim(
    claim: InboxClaim, *, lease_seconds: int = 120, timeout_seconds: int = 300
) -> bool:
    """Execute once, quarantining ambiguous results instead of retrying sends.

    Return whether the fenced database transition succeeded. Cancellation is
    best effort: a provider may already have accepted an outbound request.
    """
    if not 10 <= lease_seconds <= 900 or not 1 <= timeout_seconds <= 900:
        raise ValueError("Invalid inbox execution bounds")
    job = asyncio.create_task(_process(claim))
    heartbeat = asyncio.create_task(_heartbeat(claim, lease_seconds))
    uncertain = True
    deferred = False
    try:
        done, _ = await asyncio.wait(
            {job, heartbeat}, timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        if job in done and heartbeat not in done:
            result = job.result()
            deferred = result == HandlingOutcome.deferred
            uncertain = result not in {HandlingOutcome.accepted, HandlingOutcome.suppressed}
        else:
            logger.warning("inbox_execution_interrupted", event_id=str(claim.id))
    except asyncio.CancelledError:
        # The claim expiry reaper is the fallback if this best-effort write
        # cannot complete during shutdown or a database outage.
        with suppress(Exception):
            await asyncio.shield(finish_claim(claim.id, claim.lease_token, uncertain=True))
        raise
    except Exception as exc:
        logger.warning(
            "inbox_execution_failed", event_id=str(claim.id), error_type=type(exc).__name__
        )
    finally:
        for task in (job, heartbeat):
            if not task.done():
                task.cancel()
        await asyncio.gather(job, heartbeat, return_exceptions=True)
    if deferred:
        return await defer_claim(claim.id, claim.lease_token)
    return await finish_claim(claim.id, claim.lease_token, uncertain=uncertain)
