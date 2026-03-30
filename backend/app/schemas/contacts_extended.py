"""Extended Pydantic v2 schemas for the enriched Contacts CRM module (Wave 17).

Adds: batch tag operations, opt-in change logging (CNDP), contact interaction
history (conversations + campaigns), and segment metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AgentType,
    ConversationStatus,
    OptInStatus,
    RecipientStatus,
)

# ---------------------------------------------------------------------------
# Tags batch
# ---------------------------------------------------------------------------


class TagsBatchUpdate(BaseModel):
    """Batch add/remove tags on multiple contacts."""

    contact_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_at_least_one_operation(self) -> Self:
        if not self.add_tags and not self.remove_tags:
            msg = "Must specify add_tags or remove_tags (or both)"
            raise ValueError(msg)
        return self


class TagsBatchResult(BaseModel):
    """Result of a batch tag update."""

    updated: int


# ---------------------------------------------------------------------------
# Opt-in change (CNDP compliance)
# ---------------------------------------------------------------------------


class OptInChangeRequest(BaseModel):
    """Request to change a contact's opt-in status."""

    new_status: OptInStatus
    reason: str = Field(..., min_length=1, max_length=500)


class OptInChangeLog(BaseModel):
    """Audit record of an opt-in status change."""

    previous_status: OptInStatus
    new_status: OptInStatus
    reason: str
    changed_by: str
    changed_at: datetime


# ---------------------------------------------------------------------------
# Contact history
# ---------------------------------------------------------------------------


class ConversationSummary(BaseModel):
    """Lightweight summary of a single conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ConversationStatus
    agent_type: AgentType
    message_count: int
    started_at: datetime
    ended_at: datetime | None = None
    last_message_at: datetime | None = None


class CampaignParticipation(BaseModel):
    """A contact's participation in a single campaign."""

    campaign_id: uuid.UUID
    campaign_name: str
    status: RecipientStatus
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None


class ContactHistory(BaseModel):
    """Full interaction history for a contact."""

    contact_id: uuid.UUID
    conversations: list[ConversationSummary]
    campaigns: list[CampaignParticipation]
    total_conversations: int
    total_campaigns: int


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


class SegmentInfo(BaseModel):
    """Metadata for a predefined contact segment."""

    key: str
    label_fr: str
    label_en: str
    description_fr: str
    count: int
