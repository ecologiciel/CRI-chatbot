"""Pydantic v2 schemas for Contact CRUD."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ContactSource, Language, OptInStatus


class ContactCreate(BaseModel):
    """Schema for creating a new contact."""

    phone: str = Field(
        ..., pattern=r"^\+[1-9]\d{6,14}$",
        description="Phone in E.164 format, e.g. +212612345678",
    )
    name: str | None = Field(default=None, max_length=255)
    language: Language = Language.fr
    cin: str | None = Field(default=None, max_length=20)
    tags: list[str] = Field(default_factory=list)
    source: ContactSource = ContactSource.whatsapp

    @field_validator("cin")
    @classmethod
    def validate_cin(cls, v: str | None) -> str | None:
        """Validate Moroccan CIN format if provided."""
        if v is not None:
            import re
            if not re.match(r"^[A-Z]{1,2}\d{5,6}$", v):
                msg = "CIN must match Moroccan format: 1-2 uppercase letters + 5-6 digits"
                raise ValueError(msg)
        return v


class ContactUpdate(BaseModel):
    """Schema for updating a contact. All fields optional."""

    name: str | None = Field(default=None, max_length=255)
    language: Language | None = None
    cin: str | None = Field(default=None, max_length=20)
    opt_in_status: OptInStatus | None = None
    tags: list[str] | None = None
    source: ContactSource | None = None

    @field_validator("cin")
    @classmethod
    def validate_cin(cls, v: str | None) -> str | None:
        if v is not None:
            import re
            if not re.match(r"^[A-Z]{1,2}\d{5,6}$", v):
                msg = "CIN must match Moroccan format: 1-2 uppercase letters + 5-6 digits"
                raise ValueError(msg)
        return v


class ContactResponse(BaseModel):
    """Contact response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    name: str | None
    language: Language
    cin: str | None
    opt_in_status: OptInStatus
    tags: list[str]
    source: ContactSource
    created_at: datetime
    updated_at: datetime


class ContactList(BaseModel):
    """Paginated list of contacts."""

    items: list[ContactResponse]
    total: int
    page: int
    page_size: int
