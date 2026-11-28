"""Pydantic v2 schemas for Tenant CRUD.

IMPORTANT: TenantResponse NEVER exposes whatsapp_config (contains secrets).
Super-admin responses expose only non-secret WhatsApp channel identifiers.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TenantStatus

# Reserved slugs that would conflict with PostgreSQL schemas or internal routing
_RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "public",
        "system",
        "tenant",
        "template",
        "test",
    }
)


class WhatsAppConfig(BaseModel):
    """WhatsApp Business configuration for a tenant."""

    phone_number_id: str = Field(..., description="Meta phone number ID")
    access_token: str = Field(..., description="Meta API access token", repr=False)
    verify_token: str = Field(..., description="Webhook verification token", repr=False)
    app_secret: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    business_account_id: str = Field(default="", description="WhatsApp Business Account ID")

    model_config = ConfigDict(extra="allow")

    @field_validator("phone_number_id")
    @classmethod
    def validate_phone_number_id(cls, value: str) -> str:
        value = value.strip()
        if not value.isascii() or not value.isdecimal() or len(value) > 32:
            raise ValueError("Identifiant de numéro WhatsApp invalide")
        return value


class TenantCreate(BaseModel):
    """Schema for creating a new tenant."""

    name: str = Field(..., min_length=2, max_length=255, description="Nom complet du CRI")
    slug: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern=r"^[a-z][a-z0-9]*$",
        description="Identifiant unique en minuscules et chiffres, commençant par une lettre",
    )
    region: str = Field(..., min_length=2, max_length=255, description="Region couverte")
    logo_url: str | None = Field(default=None, description="URL logo")
    accent_color: str | None = Field(default=None, description="CSS HSL color")
    whatsapp_config: WhatsAppConfig | None = Field(default=None, description="Config WhatsApp")
    public_config: dict = Field(
        default_factory=dict, description="Configuration publique sans secrets"
    )
    is_demo: bool = Field(default=False, description="Active la rétention courte de démonstration")
    conversation_retention_days: int = Field(default=90, ge=1, le=3650)
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
    public_config: dict | None = None
    is_demo: bool | None = None
    conversation_retention_days: int | None = Field(default=None, ge=1, le=3650)
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
    public_config: dict
    is_demo: bool
    conversation_retention_days: int
    status: TenantStatus
    max_contacts: int
    max_messages_per_year: int
    max_admins: int
    created_at: datetime
    updated_at: datetime

    # NOTE: whatsapp_config is intentionally EXCLUDED

    model_config = ConfigDict(from_attributes=True)


class WhatsAppConfigView(BaseModel):
    """Allowlisted channel identifiers; credentials and unknown keys stay private."""

    phone_number_id: str | None = None
    business_account_id: str | None = None

    model_config = ConfigDict(extra="ignore")


class TenantAdminResponse(TenantResponse):
    """Super-admin response with non-secret WhatsApp channel identifiers."""

    whatsapp_config: WhatsAppConfigView | None = None

    model_config = ConfigDict(from_attributes=True)


class TenantList(BaseModel):
    """Paginated list of tenants."""

    items: list[TenantResponse]
    total: int
    page: int
    page_size: int
