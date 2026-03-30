"""Conversation and Message models — stored in the TENANT schema.

A conversation groups messages between a contact and the platform.
Message.timestamp = delivery time; Message.created_at = record creation time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import (
    AgentType,
    ConversationStatus,
    MessageDirection,
    MessageType,
)

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.escalation import Escalation
    from app.models.feedback import Feedback


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_contact_id", "contact_id"),
        Index("ix_conversations_status", "status"),
        Index("ix_conversations_started_at", "started_at"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agenttype", schema="public"),
        nullable=False,
        default=AgentType.public,
        server_default=AgentType.public.value,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversationstatus", schema="public"),
        nullable=False,
        default=ConversationStatus.active,
        server_default=ConversationStatus.active.value,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    contact: Mapped[Contact] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    escalations: Mapped[list[Escalation]] = relationship(
        back_populates="conversation",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} status={self.status.value}>"


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
        Index(
            "ix_messages_whatsapp_message_id",
            "whatsapp_message_id",
            unique=True,
            postgresql_where=text("whatsapp_message_id IS NOT NULL"),
        ),
        Index("ix_messages_timestamp", "timestamp"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="messagedirection", schema="public"),
        nullable=False,
    )
    type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="messagetype", schema="public"),
        nullable=False,
        default=MessageType.text,
        server_default=MessageType.text.value,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_ids: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    whatsapp_message_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Message delivery time (distinct from created_at)",
    )

    # Relationships
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Message id={self.id} direction={self.direction.value}>"
