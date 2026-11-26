"""Staged encrypted provider delivery notifications, scoped to an institution."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class WhatsAppStatusEvent(UUIDMixin, Base):
    __tablename__ = "whatsapp_status_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'applied', 'uncertain', 'follow_up', 'resolved')",
            name="ck_wa_status_state",
        ),
        CheckConstraint("key_version > 0 AND attempts >= 0", name="ck_wa_status_counters"),
        Index("uq_wa_status_fingerprint", "tenant_id", "fingerprint", unique=True),
        Index("ix_wa_status_pending", "state", "next_attempt_at"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False
    )
    phone_number_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
