"""Fenced claims for a staged durable inbox.

An expired claim is quarantined as uncertain, never automatically resent.
Fencing protects database state; it cannot cancel an external Meta request.
No production worker uses this module yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from app.core.database import get_session_factory
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.services.whatsapp.conversation_lock import try_lock_for_claim


@dataclass(frozen=True, slots=True)
class InboxClaim:
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone_number_id: str
    provider_message_id: str
    key_version: int
    ciphertext: str
    lease_token: uuid.UUID
    lease_until: datetime
    sender_fingerprint: str = ""
    is_opt_out: bool = False


def _lease_duration(seconds: int) -> timedelta:
    if not 10 <= seconds <= 900:
        raise ValueError("Lease duration must be between 10 and 900 seconds")
    return timedelta(seconds=seconds)


async def claim_next(*, lease_seconds: int = 120) -> InboxClaim | None:
    duration = _lease_duration(lease_seconds)
    token = uuid.uuid4()
    earlier, running, legacy = (aliased(WhatsAppInboxEvent) for _ in range(3))
    unresolved = ("pending", "processing", "uncertain", "follow_up")
    candidate = WhatsAppInboxEvent
    # Legacy ungrouped events block only their own tenant until reconciled.
    candidates = (
        select(candidate.id, candidate.tenant_id, candidate.sender_fingerprint)
        .where(
            candidate.state == "pending",
            candidate.sender_fingerprint.is_not(None),
            or_(candidate.not_before.is_(None), candidate.not_before <= func.clock_timestamp()),
            or_(candidate.is_opt_out.is_(True), ~exists(select(1).where(
                    earlier.tenant_id == candidate.tenant_id,
                    earlier.sender_fingerprint == candidate.sender_fingerprint,
                    earlier.arrival_sequence < candidate.arrival_sequence,
                    earlier.state.in_(unresolved),
            ))),
            ~exists(select(1).where(
                running.tenant_id == candidate.tenant_id,
                running.sender_fingerprint == candidate.sender_fingerprint,
                running.state == "processing",
            )),
            ~exists(select(1).where(
                legacy.tenant_id == candidate.tenant_id,
                legacy.sender_fingerprint.is_(None),
                or_(legacy.state == "processing",
                    and_(candidate.is_opt_out.is_(False), legacy.state.in_(unresolved))),
            )),
        )
        .order_by(candidate.arrival_sequence)
        .limit(100)
    )
    row = None
    async with get_session_factory()() as session:
        for event_id, tenant_id, fingerprint, is_opt_out in (await session.execute(
            candidates.add_columns(candidate.is_opt_out)
        )).all():
            if not await try_lock_for_claim(session, tenant_id, fingerprint):
                continue
            # Re-read after acquiring the stream lock: the candidate query may
            # have used a snapshot from before another claim or acceptance.
            ungrouped = await session.scalar(select(exists().where(
                candidate.tenant_id == tenant_id,
                candidate.sender_fingerprint.is_(None),
                candidate.state.in_(("processing",) if is_opt_out else unresolved),
            )))
            if ungrouped:
                continue
            active = await session.scalar(select(exists().where(
                candidate.tenant_id == tenant_id,
                candidate.sender_fingerprint == fingerprint,
                candidate.state == "processing",
            )))
            if active:
                continue
            first_query = (
                select(candidate.id, candidate.state)
                .where(candidate.tenant_id == tenant_id,
                       candidate.sender_fingerprint == fingerprint,
                       candidate.state.in_(unresolved))
            )
            if is_opt_out:
                first_query = first_query.where(candidate.state == "pending", candidate.is_opt_out.is_(True))
            first = (await session.execute(first_query.order_by(candidate.arrival_sequence).limit(1))).one_or_none()
            if first is None or first.id != event_id or first.state != "pending":
                continue
            # Do not skip to a later event if an unrelated transaction has
            # locked the first row for review or retention.
            locked = (await session.execute(
                select(candidate.id).where(
                    candidate.id == event_id, candidate.state == "pending",
                    or_(candidate.not_before.is_(None), candidate.not_before <= func.clock_timestamp()),
                )
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if locked is None:
                continue
            statement = (
                update(candidate)
                .execution_options(synchronize_session=False)
                .where(candidate.id == event_id, candidate.state == "pending")
                .values(state="processing", attempts=candidate.attempts + 1, not_before=None,
                        lease_token=token, lease_until=func.clock_timestamp() + duration,
                        updated_at=func.clock_timestamp())
                .returning(candidate.id, candidate.tenant_id, candidate.phone_number_id,
                           candidate.provider_message_id, candidate.key_version,
                           candidate.ciphertext, candidate.lease_until, candidate.sender_fingerprint,
                           candidate.is_opt_out)
            )
            row = (await session.execute(statement)).one_or_none()
            if row is not None:
                break
        await session.commit()
    if row is None:
        return None
    return InboxClaim(
        id=row.id,
        tenant_id=row.tenant_id,
        phone_number_id=row.phone_number_id,
        provider_message_id=row.provider_message_id,
        key_version=row.key_version,
        ciphertext=row.ciphertext,
        lease_token=token,
        lease_until=row.lease_until,
        sender_fingerprint=row.sender_fingerprint,
        is_opt_out=row.is_opt_out,
    )


async def renew_claim(event_id: uuid.UUID, token: uuid.UUID, *, lease_seconds: int = 120) -> bool:
    duration = _lease_duration(lease_seconds)
    statement = (
        update(WhatsAppInboxEvent)
        .execution_options(synchronize_session=False)
        .where(
            WhatsAppInboxEvent.id == event_id,
            WhatsAppInboxEvent.state == "processing",
            WhatsAppInboxEvent.lease_token == token,
            WhatsAppInboxEvent.lease_until > func.clock_timestamp(),
        )
        .values(lease_until=func.clock_timestamp() + duration, updated_at=func.clock_timestamp())
        .returning(WhatsAppInboxEvent.id)
    )
    async with get_session_factory()() as session:
        updated = (await session.execute(statement)).scalar_one_or_none() is not None
        await session.commit()
    return updated


async def finish_claim(event_id: uuid.UUID, token: uuid.UUID, *, uncertain: bool) -> bool:
    predicates = [
        WhatsAppInboxEvent.id == event_id,
        WhatsAppInboxEvent.state == "processing",
        WhatsAppInboxEvent.lease_token == token,
    ]
    if not uncertain:
        predicates.append(WhatsAppInboxEvent.lease_until > func.clock_timestamp())
    statement = (
        update(WhatsAppInboxEvent)
        .execution_options(synchronize_session=False)
        .where(*predicates)
        .values(
            state="uncertain" if uncertain else "completed",
            lease_token=None,
            lease_until=None,
            updated_at=func.clock_timestamp(),
        )
        .returning(WhatsAppInboxEvent.id)
    )
    async with get_session_factory()() as session:
        updated = (await session.execute(statement)).scalar_one_or_none() is not None
        await session.commit()
    return updated


async def defer_claim(event_id: uuid.UUID, token: uuid.UUID, *, delay_seconds: int = 60) -> bool:
    """Return a side-effect-free claim to its ordered queue after a bounded delay."""
    if not 1 <= delay_seconds <= 900:
        raise ValueError("Invalid inbox defer duration")
    statement = (
        update(WhatsAppInboxEvent)
        .execution_options(synchronize_session=False)
        .where(
            WhatsAppInboxEvent.id == event_id,
            WhatsAppInboxEvent.state == "processing",
            WhatsAppInboxEvent.lease_token == token,
            WhatsAppInboxEvent.lease_until > func.clock_timestamp(),
        )
        .values(
            state="pending", lease_token=None, lease_until=None,
            not_before=func.clock_timestamp() + timedelta(seconds=delay_seconds),
            updated_at=func.clock_timestamp(),
        )
        .returning(WhatsAppInboxEvent.id)
    )
    async with get_session_factory()() as session:
        updated = (await session.execute(statement)).scalar_one_or_none() is not None
        await session.commit()
    return updated


async def quarantine_expired(*, limit: int = 100) -> int:
    """Move expired claims to manual review without creating another send."""
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid quarantine batch size")
    candidates = (
        select(WhatsAppInboxEvent.id)
        .where(
            WhatsAppInboxEvent.state == "processing",
            WhatsAppInboxEvent.lease_until <= func.clock_timestamp(),
        )
        .order_by(WhatsAppInboxEvent.lease_until, WhatsAppInboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    statement = (
        update(WhatsAppInboxEvent)
        .execution_options(synchronize_session=False)
        .where(WhatsAppInboxEvent.id.in_(candidates), WhatsAppInboxEvent.state == "processing")
        .values(
            state="uncertain", lease_token=None, lease_until=None, updated_at=func.clock_timestamp()
        )
        .returning(WhatsAppInboxEvent.id)
    )
    async with get_session_factory()() as session:
        ids = (await session.execute(statement)).scalars().all()
        await session.commit()
    return len(ids)
