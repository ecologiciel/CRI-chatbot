"""Pydantic v2 schemas for Tenant CRUD.

IMPORTANT: TenantResponse NEVER exposes whatsapp_config (contains secrets).
Use TenantAdminResponse for super-admin endpoints that need WhatsApp config.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TenantStatus

# Reserved slugs that would conflict with PostgreSQL schemas or internal routing
_RESERVED_SLUGS = frozenset({
    "admin", "api", "public", "system", "tenant", "test",
})


class WhatsAppConfig(BaseModel):
    """WhatsApp Business configuration for a tenant."""

    phone_number_id: str = Field(..., description="Meta phone number ID")
    access_token: str = Field(..., description="Meta API access token")
    verify_token: str = Field(..., description="Webhook verification token")
    business_account_id: str = Field(
        default="", description="WhatsApp Business Account ID"
    )

    model_config = ConfigDict(extra="allow")


class TenantCreate(BaseModel):
    """Schema for creating a new tenant."""

    name: str = Field(..., min_length=2, max_length=255, description="Nom complet du CRI")
    slug: str = Field(
        ..., min_length=2, max_length=50,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="Identifiant unique (lowercase, alphanumeric, hyphens)",
    )
    region: str = Field(..., min_length=2, max_length=255, description="Region couverte")
    logo_url: str | None = Field(default=None, description="URL logo")
    accent_color: str | None = Field(default=None, description="CSS HSL color")
    whatsapp_config: WhatsAppConfig | None = Field(
        default=None, description="Config WhatsApp"
    )
    max_contacts: int = Field(default=20_000, ge=100, le=1_000_000)
    max_messages_per_year: int = Field(default=100_000, ge=1000, le=10_000_000)
    max_admins: int = Field(default=10, ge=1, le=100)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if v in _RESERVED_SLUGS:
            msg = f"Slug '{v}' is reserved"
            raise ValueError(msg)
        return v.lower()


class TenantUpdate(BaseModel):
    """Schema for updating a tenant. All fields optional."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    region: str | None = Field(default=None, min_length=2, max_length=255)
    logo_url: str | None = None
    accent_color: str | None = None
    whatsapp_config: WhatsAppConfig | None = None
    status: TenantStatus | None = None
    max_contacts: int | None = Field(default=None, ge=100, le=1_000_000)
    max_messages_per_year: int | None = Field(default=None, ge=1000, le=10_000_000)
    max_admins: int | None = Field(default=None, ge=1, le=100)


class TenantResponse(BaseModel):
    """Public tenant response — NO secrets exposed."""

    id: uuid.UUID
    name: str
    slug: str
    region: str
    logo_url: str | None
    accent_color: str | None
    status: TenantStatus
    max_contacts: int
    max_messages_per_year: int
    max_admins: int
    created_at: datetime
    updated_at: datetime

    # NOTE: whatsapp_config is intentionally EXCLUDED

    model_config = ConfigDict(from_attributes=True)


class TenantAdminResponse(TenantResponse):
    """Super-admin response — includes WhatsApp config."""

    whatsapp_config: WhatsAppConfig | None = None

    model_config = ConfigDict(from_attributes=True)


class TenantList(BaseModel):
    """Paginated list of tenants."""

    items: list[TenantResponse]
    total: int
    page: int
    page_size: int
