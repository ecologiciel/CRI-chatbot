"""Pydantic v2 schemas for Conversation and Message CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AgentType,
    ConversationStatus,
    MessageDirection,
    MessageType,
)


class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""

    contact_id: uuid.UUID
    agent_type: AgentType = AgentType.public


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation. All fields optional."""

    status: ConversationStatus | None = None
    ended_at: datetime | None = None


class ConversationResponse(BaseModel):
    """Conversation response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    agent_type: AgentType
    status: ConversationStatus
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    """Paginated list of conversations."""

    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int


# --- Message schemas ---


class MessageCreate(BaseModel):
    """Schema for creating a new message."""

    conversation_id: uuid.UUID
    direction: MessageDirection
    type: MessageType = MessageType.text
    content: str | None = Field(default=None, max_length=10000)
    media_url: str | None = Field(default=None, max_length=500)
    whatsapp_message_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_content_or_media(self) -> MessageCreate:
        """At least one of content or media_url must be provided."""
        if self.content is None and self.media_url is None:
            msg = "At least one of 'content' or 'media_url' must be provided"
            raise ValueError(msg)
        return self


class MessageResponse(BaseModel):
    """Message response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    direction: MessageDirection
    type: MessageType
    content: str | None
    media_url: str | None
    chunk_ids: list
    whatsapp_message_id: str | None
    timestamp: datetime
    created_at: datetime
