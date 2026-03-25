"""Feedback and UnansweredQuestion models — stored in the TENANT schema.

Feedback: user rating on a specific message response (thumbs up/down/question).
UnansweredQuestion: questions the RAG pipeline couldn't answer confidently.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import FeedbackRating, UnansweredStatus

if TYPE_CHECKING:
    from app.models.conversation import Message


class Feedback(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_message_id", "message_id"),
        Index("ix_feedback_rating", "rating"),
        Index("ix_feedback_created_at", "created_at"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(FeedbackRating, name="feedbackrating", schema="public"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )

    # Relationships
    message: Mapped[Message] = relationship(back_populates="feedback")

    def __repr__(self) -> str:
        return f"<Feedback rating={self.rating.value} message={self.message_id}>"


class UnansweredQuestion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "unanswered_questions"
    __table_args__ = (
        Index("ix_unanswered_questions_status", "status"),
        Index("ix_unanswered_questions_status_freq", "status", "frequency"),
        Index("ix_unanswered_questions_language", "language"),
        Index("ix_unanswered_questions_created_at", "created_at"),
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="fr",
    )
    frequency: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    proposed_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[UnansweredStatus] = mapped_column(
        Enum(UnansweredStatus, name="unansweredstatus", schema="public"),
        nullable=False,
        default=UnansweredStatus.pending,
        server_default=UnansweredStatus.pending.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="Reference only — no FK (conversation may be deleted)",
    )

    def __repr__(self) -> str:
        return f"<UnansweredQuestion status={self.status.value} freq={self.frequency}>"
