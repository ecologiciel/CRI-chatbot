"""Fence durable conversation sends against STOP and expired claims.

An in-flight provider request cannot be recalled. The shared PostgreSQL lock
ensures it starts before STOP commits or is suppressed after STOP commits.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.core.tenant import TenantContext
from app.models.audit import AuditLog
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.services.whatsapp.conversation_lock import lock_for_acceptance
from app.services.whatsapp.inbox_leases import InboxClaim


class OutboundFenceError(RuntimeError):
    """A durable send is unsafe or its claim is no longer valid."""


class OutboundSupersededError(OutboundFenceError):
    """A newer committed STOP makes an older response ineligible."""


@dataclass(slots=True)
class OutboundScope:
    claim: InboxClaim
    recipient: str
    suppressed: bool = False
    uncertain: bool = False


_scope: ContextVar[OutboundScope | None] = ContextVar("wa_outbound_scope", default=None)


def mark_outbound_uncertain() -> None:
    scope = _scope.get()
    if scope is not None:
        scope.uncertain = True


@contextmanager
def outbound_scope(claim: InboxClaim, recipient: str) -> Iterator[OutboundScope]:
    scope = OutboundScope(claim=claim, recipient=recipient)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


@asynccontextmanager
async def guarded_provider_send(tenant: TenantContext, recipient: str) -> AsyncIterator[None]:
    """Hold the stream lock over a bounded provider call for durable work only."""
    scope = _scope.get()
    if scope is None:
        yield
        return
    if scope.suppressed:
        raise OutboundSupersededError("Response superseded by opt-out")
    claim = scope.claim
    if tenant.id != claim.tenant_id or recipient != scope.recipient:
        raise OutboundFenceError("Durable outbound context mismatch")
    # Covers lock wait, database checks and the complete outbound request.
    async with asyncio.timeout(40):
        async with get_session_factory()() as session:
            await lock_for_acceptance(session, claim.tenant_id, claim.sender_fingerprint)
            sequence = (
                await session.execute(
                    select(WhatsAppInboxEvent.arrival_sequence)
                    .where(
                        WhatsAppInboxEvent.id == claim.id,
                        WhatsAppInboxEvent.tenant_id == claim.tenant_id,
                        WhatsAppInboxEvent.phone_number_id == claim.phone_number_id,
                        WhatsAppInboxEvent.sender_fingerprint == claim.sender_fingerprint,
                        WhatsAppInboxEvent.state == "processing",
                        WhatsAppInboxEvent.lease_token == claim.lease_token,
                        WhatsAppInboxEvent.lease_until > func.clock_timestamp(),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if sequence is None:
                raise OutboundFenceError("Durable outbound claim unavailable")
            newer_stop = (
                await session.execute(
                    select(WhatsAppInboxEvent.id)
                    .where(
                        WhatsAppInboxEvent.tenant_id == claim.tenant_id,
                        WhatsAppInboxEvent.sender_fingerprint == claim.sender_fingerprint,
                        WhatsAppInboxEvent.arrival_sequence > sequence,
                        WhatsAppInboxEvent.is_opt_out.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if newer_stop is not None:
                session.add(
                    AuditLog(
                        tenant_slug=tenant.slug,
                        user_type="system",
                        action="wa_send_suppressed",
                        resource_type="whatsapp_inbox_event",
                        resource_id=str(claim.id),
                        details={"reason": "newer_opt_out"},
                    )
                )
                await session.commit()
                scope.suppressed = True
                raise OutboundSupersededError("Response superseded by opt-out")
            # The lock stays held until the provider call returns or fails.
            try:
                yield
                await session.commit()
            except BaseException:
                # Once control has entered the provider call, cancellation or
                # failure cannot prove that the provider did not accept it.
                scope.uncertain = True
                raise
