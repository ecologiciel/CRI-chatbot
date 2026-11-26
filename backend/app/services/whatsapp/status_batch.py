"""Bounded, restart-safe processing for staged delivery status events."""

from __future__ import annotations

from datetime import timedelta

import structlog
from sqlalchemy import case, func, select, update

from app.core.database import get_session_factory
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.status_projection import apply_status_event

logger = structlog.get_logger()


async def _defer_error(event_id) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            update(WhatsAppStatusEvent)
            .execution_options(synchronize_session=False)
            .where(
                WhatsAppStatusEvent.id == event_id,
                WhatsAppStatusEvent.state == "pending",
                WhatsAppStatusEvent.next_attempt_at <= func.clock_timestamp(),
            )
            .values(
                attempts=WhatsAppStatusEvent.attempts + 1,
                state=case((WhatsAppStatusEvent.attempts + 1 >= 12, "uncertain"), else_="pending"),
                next_attempt_at=func.clock_timestamp() + timedelta(minutes=5),
                updated_at=func.clock_timestamp(),
            )
        )
        await session.commit()


async def run_status_batch(*, cipher: VersionedEnvelopeService, limit: int = 50) -> dict[str, int]:
    """Apply a bounded set of due events; leave failures retriable with backoff."""
    if not 1 <= limit <= 250:
        raise ValueError("Invalid status batch size")
    async with get_session_factory()() as session:
        ids = (
            (
                await session.execute(
                    select(WhatsAppStatusEvent.id)
                    .where(
                        WhatsAppStatusEvent.state == "pending",
                        WhatsAppStatusEvent.next_attempt_at <= func.clock_timestamp(),
                    )
                    .order_by(WhatsAppStatusEvent.next_attempt_at, WhatsAppStatusEvent.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    counts: dict[str, int] = {}
    for event_id in ids:
        try:
            result = await apply_status_event(event_id, cipher=cipher)
        except Exception as exc:
            logger.warning(
                "wa_status_projection_failed", event_id=str(event_id), error_type=type(exc).__name__
            )
            await _defer_error(event_id)
            result = "error"
        counts[result] = counts.get(result, 0) + 1
    return counts
