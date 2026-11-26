"""Fenced claims for a staged durable inbox.

An expired claim is quarantined as uncertain, never automatically resent.
Fencing protects database state; it cannot cancel an external Meta request.
No production worker uses this module yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.core.database import get_session_factory
from app.models.whatsapp_inbox import WhatsAppInboxEvent


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


def _lease_duration(seconds: int) -> timedelta:
    if not 10 <= seconds <= 900:
        raise ValueError("Lease duration must be between 10 and 900 seconds")
    return timedelta(seconds=seconds)


async def claim_next(*, lease_seconds: int = 120) -> InboxClaim | None:
    duration = _lease_duration(lease_seconds)
    token = uuid.uuid4()
    candidate = (
        select(WhatsAppInboxEvent.id)
        .where(WhatsAppInboxEvent.state == "pending")
        .order_by(WhatsAppInboxEvent.created_at, WhatsAppInboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .scalar_subquery()
    )
    statement = (
        update(WhatsAppInboxEvent)
        .execution_options(synchronize_session=False)
        .where(WhatsAppInboxEvent.id == candidate, WhatsAppInboxEvent.state == "pending")
        .values(
            state="processing",
            attempts=WhatsAppInboxEvent.attempts + 1,
            lease_token=token,
            lease_until=func.clock_timestamp() + duration,
            updated_at=func.clock_timestamp(),
        )
        .returning(
            WhatsAppInboxEvent.id,
            WhatsAppInboxEvent.tenant_id,
            WhatsAppInboxEvent.phone_number_id,
            WhatsAppInboxEvent.provider_message_id,
            WhatsAppInboxEvent.key_version,
            WhatsAppInboxEvent.ciphertext,
            WhatsAppInboxEvent.lease_until,
        )
    )
    async with get_session_factory()() as session:
        row = (await session.execute(statement)).one_or_none()
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
