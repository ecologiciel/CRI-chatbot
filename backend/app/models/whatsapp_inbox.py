"""Durable encrypted WhatsApp ingress records in the shared schema.

Processing is intentionally not wired to this model yet. The ciphertext is
bound to the tenant UUID and record UUID by VersionedEnvelopeService.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class WhatsAppInboxEvent(UUIDMixin, Base):
    __tablename__ = "whatsapp_inbox_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'processing', 'uncertain', 'follow_up', 'resolved', 'completed')",
            name="ck_wa_inbox_state",
        ),
        CheckConstraint("key_version > 0 AND attempts >= 0", name="ck_wa_inbox_counters"),
        CheckConstraint(
            "(state = 'processing' AND lease_until IS NOT NULL AND lease_token IS NOT NULL) "
            "OR (state <> 'processing' AND lease_until IS NULL AND lease_token IS NULL)",
            name="ck_wa_inbox_lease",
        ),
        Index("uq_wa_inbox_tenant_message", "tenant_id", "provider_message_id", unique=True),
        Index("ix_wa_inbox_pending", "state", "created_at"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
