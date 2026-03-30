"""Escalation model — stored in the TENANT schema.

An escalation routes a conversation to a human CRI agent when the AI
pipeline cannot handle it.  Six trigger scenarios are supported:
explicit user request, repeated RAG failure, sensitive topic, negative
feedback, OTP timeout, and manual back-office intervention.

Lifecycle: pending → assigned → in_progress → resolved / closed
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDMixin
from app.models.enums import EscalationPriority, EscalationStatus, EscalationTrigger

if TYPE_CHECKING:
    from app.models.admin import Admin
    from app.models.conversation import Conversation


class Escalation(UUIDMixin, Base):
    """Escalade d'une conversation vers un agent humain CRI.

    Created when one of the 6 trigger scenarios fires — either
    automatically by the AI pipeline or manually from the back-office.

    Attributes:
        conversation_id: The conversation being escalated.
        assigned_to: Admin who picked up the escalation (nullable).
        trigger_type: Which of the 6 scenarios caused the escalation.
        priority: Queue sort order (high → medium → low).
        context_summary: AI-generated summary of the conversation history.
        user_message: Last user message before escalation.
        status: Current lifecycle stage.
        resolution_notes: Notes left by the human agent on resolution.
        created_at: When the escalation was created.
        assigned_at: When an agent picked it up.
        resolved_at: When the escalation was resolved or closed.
    """

    __tablename__ = "escalations"
    __table_args__ = (
        Index("ix_escalations_status_priority", "status", "priority"),
        Index("ix_escalations_assigned_to", "assigned_to"),
        Index(
            "ix_escalations_created_at",
            "created_at",
            postgresql_using="btree",
        ),
        Index("ix_escalations_conversation_id", "conversation_id"),
    )

    # ── Foreign keys ──────────────────────────────────────────────
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.admins.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Trigger & priority ────────────────────────────────────────
    trigger_type: Mapped[EscalationTrigger] = mapped_column(
        Enum(EscalationTrigger, name="escalationtrigger", schema="public"),
        nullable=False,
    )
    priority: Mapped[EscalationPriority] = mapped_column(
        Enum(EscalationPriority, name="escalationpriority", schema="public"),
        nullable=False,
    )

    # ── Context ───────────────────────────────────────────────────
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Status ────────────────────────────────────────────────────
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus, name="escalationstatus", schema="public"),
        nullable=False,
        default=EscalationStatus.pending,
        server_default=EscalationStatus.pending.value,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps (no TimestampMixin — no updated_at needed) ────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────
    conversation: Mapped[Conversation] = relationship(
        back_populates="escalations",
    )
    agent: Mapped[Admin | None] = relationship(
        foreign_keys=[assigned_to],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Escalation id={self.id} "
            f"trigger={self.trigger_type.value} "
            f"status={self.status.value}>"
        )
