"""Pydantic v2 schemas for Campaign and CampaignRecipient CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CampaignStatus, RecipientStatus

# ─── Campaign schemas ───────────────────────────────────────────────


class CampaignCreate(BaseModel):
    """Schema for creating a new campaign.

    audience_filter must contain at least one criterion (e.g. tags, language).
    Contacts with opt_in_status = opted_out are excluded at the service layer.
    """

    name: str = Field(..., min_length=1, max_length=200, description="Campaign name")
    description: str | None = Field(default=None, description="Optional description")
    template_id: str = Field(..., description="Meta template ID")
    template_name: str = Field(..., description="Human-readable template name")
    template_language: str = Field(default="fr", description="Template language code")
    audience_filter: dict = Field(
        ..., description="Targeting criteria: tags, segments, language, etc."
    )
    variable_mapping: dict = Field(
        default_factory=dict, description='Template variable mapping: {"1": "contact.name", ...}'
    )

    @model_validator(mode="after")
    def validate_audience_filter(self) -> CampaignCreate:
        """Vérifie que audience_filter contient au moins un critère."""
        if not self.audience_filter:
            raise ValueError("audience_filter must contain at least one criterion")
        return self


class CampaignUpdate(BaseModel):
    """Schema for updating a campaign. All fields optional.

    Only editable when campaign status is 'draft' (enforced at service layer).
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    audience_filter: dict | None = None
    variable_mapping: dict | None = None


class CampaignRead(BaseModel):
    """Full campaign response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    template_id: str
    template_name: str
    template_language: str
    audience_filter: dict
    audience_count: int
    variable_mapping: dict
    status: CampaignStatus
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    stats: dict
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CampaignList(BaseModel):
    """Paginated list of campaigns."""

    items: list[CampaignRead]
    total: int
    page: int
    page_size: int


class CampaignSchedule(BaseModel):
    """Schema for scheduling a campaign send."""

    scheduled_at: datetime = Field(..., description="When to start sending (UTC)")


# ─── Recipient schemas ───────────────────────────────────────────────


class RecipientRead(BaseModel):
    """Campaign recipient response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    status: RecipientStatus
    whatsapp_message_id: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    error_message: str | None
    created_at: datetime


class RecipientList(BaseModel):
    """Paginated list of campaign recipients."""

    items: list[RecipientRead]
    total: int
    page: int
    page_size: int


# ─── Stats schemas ───────────────────────────────────────────────────


class CampaignStats(BaseModel):
    """Aggregated campaign delivery statistics."""

    total: int
    sent: int
    delivered: int
    read: int
    failed: int
    pending: int
    delivery_rate: float | None = None
    read_rate: float | None = None


class AudiencePreview(BaseModel):
    """Preview of targeted audience before sending."""

    count: int = Field(..., description="Total contacts matching the filter")
    sample: list[dict] = Field(
        default_factory=list,
        description="Sample of up to 5 matching contacts",
    )
