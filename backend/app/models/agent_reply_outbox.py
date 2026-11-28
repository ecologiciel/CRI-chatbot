"""Encrypted, tenant-bound intents for agent messages (staged only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class AgentReplyOutboxEvent(UUIDMixin, Base):
    __tablename__ = "agent_reply_outbox_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'processing', 'accepted', 'uncertain', 'follow_up', 'resolved', 'canceled')",
            name="ck_agent_reply_state",
        ),
        CheckConstraint("attempts IN (0, 1) AND key_version > 0", name="ck_agent_reply_counters"),
        CheckConstraint("state <> 'pending' OR attempts = 0", name="ck_agent_reply_no_requeue"),
        CheckConstraint(
            "state <> 'accepted' OR redacted_at IS NOT NULL OR (provider_message_id IS NOT NULL AND length(provider_message_id) > 0)",
            name="ck_agent_reply_accepted_id",
        ),
        CheckConstraint(
            "(state = 'resolved' AND review_decision IS NOT NULL AND review_decision IN ('confirmed_delivered', 'confirmed_not_sent', 'unknown_no_retry') "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) OR "
            "(state <> 'resolved' AND review_decision IS NULL AND reviewed_by IS NULL AND reviewed_at IS NULL)",
            name="ck_agent_reply_review",
        ),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_agent_reply_lease",
        ),
        CheckConstraint(
            "(redacted_at IS NULL AND contact_id IS NOT NULL AND phone_number_id IS NOT NULL "
            "AND recipient_fingerprint IS NOT NULL AND recipient_fingerprint ~ '^[0-9a-f]{64}$') OR "
            "(redacted_at IS NOT NULL AND contact_id IS NULL AND phone_number_id IS NULL "
            "AND recipient_fingerprint IS NULL)", name="ck_agent_reply_recipient",
        ),
        CheckConstraint(
            "redacted_at IS NULL OR (state IN ('accepted', 'resolved', 'canceled') "
            "AND ciphertext = '' AND provider_message_id IS NULL)", name="ck_agent_reply_redaction",
        ),
        Index("uq_agent_reply_request", "tenant_id", "request_key", unique=True),
        Index("uq_agent_reply_sequence", "sequence", unique=True),
        Index("ix_agent_reply_queue", "state", "created_at"),
        Index("ix_agent_reply_conversation", "tenant_id", "conversation_id", "sequence"),
        Index(
            "ix_agent_reply_retention", "tenant_id", "updated_at", "id",
            postgresql_where=text("redacted_at IS NULL AND state IN ('accepted', 'resolved', 'canceled')"),
        ),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="RESTRICT"), nullable=False
    )
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    escalation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    phone_number_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recipient_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    outcome_code: Mapped[str | None] = mapped_column(String(64))
    review_decision: Mapped[str | None] = mapped_column(String(32))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
