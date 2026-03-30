"""Pydantic v2 schemas for InternalWhitelist CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InternalWhitelistCreate(BaseModel):
    """Schema for adding a phone number to the internal whitelist."""

    phone: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{6,14}$",
        description="Phone in E.164 format, e.g. +212612345678",
    )
    label: str | None = Field(default=None, max_length=255)
    note: str | None = None


class InternalWhitelistUpdate(BaseModel):
    """Schema for updating a whitelist entry. All fields optional."""

    label: str | None = Field(default=None, max_length=255)
    note: str | None = None
    is_active: bool | None = None


class InternalWhitelistResponse(BaseModel):
    """Whitelist entry response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    label: str | None
    note: str | None
    is_active: bool
    added_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class InternalWhitelistList(BaseModel):
    """Paginated list of whitelist entries."""

    items: list[InternalWhitelistResponse]
    total: int
    page: int
    page_size: int


class WhitelistCheckResponse(BaseModel):
    """Quick check: is a phone number whitelisted and active?"""

    phone: str
    is_whitelisted: bool
