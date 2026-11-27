"""Durable dossier notification intents; rows contain references, not message text."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class NotificationOutboxEvent(UUIDMixin, Base):
    """One tenant-scoped intent for an immutable dossier-history change."""

    __tablename__ = "notification_outbox_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'processing', 'sent', 'skipped', 'uncertain')",
            name="ck_notification_outbox_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_notification_outbox_lease",
        ),
        Index("uq_notification_outbox_history", "tenant_id", "history_id", unique=True),
        Index("ix_notification_outbox_queue", "tenant_id", "state", "created_at"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False
    )
    # History lives in a tenant-specific schema, so a cross-schema FK cannot be static.
    history_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
