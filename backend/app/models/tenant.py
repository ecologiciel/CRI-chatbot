"""Tenant model — stored in the PUBLIC schema (shared across all tenants).

Each tenant represents a CRI (Centre Regional d'Investissement).
The slug is the routing key used everywhere:
  - PostgreSQL schema: tenant_{slug}
  - Qdrant collection: kb_{slug}
  - Redis prefix: {slug}:
  - MinIO bucket: cri-{slug}
"""

from sqlalchemy import Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import TenantStatus


class Tenant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        Index("ix_tenants_slug", "slug", unique=True),
        Index("ix_tenants_status", "status"),
        {"schema": "public"},
    )

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Nom complet du CRI")
    slug: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="Identifiant unique de routage multi-tenant",
    )
    region: Mapped[str] = mapped_column(String(255), nullable=False, comment="Region couverte")

    # Branding
    logo_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="URL logo SVG/PNG max 200x60"
    )
    accent_color: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="CSS HSL color pour tenant accent"
    )

    # WhatsApp configuration (SENSITIVE — never expose in public APIs)
    whatsapp_config: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="phone_number_id, access_token, verify_token, templates",
    )

    # Status
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenantstatus", schema="public"),
        nullable=False,
        default=TenantStatus.provisioning,
        server_default=TenantStatus.provisioning.value,
    )

    # Limits
    max_contacts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20_000,
        server_default="20000",
    )
    max_messages_per_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100_000,
        server_default="100000",
    )
    max_admins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        server_default="10",
    )

    def __repr__(self) -> str:
        return f"<Tenant slug={self.slug!r} status={self.status.value}>"

    @property
    def db_schema(self) -> str:
        """PostgreSQL schema name for this tenant's tables."""
        return f"tenant_{self.slug}"

    @property
    def qdrant_collection(self) -> str:
        """Qdrant collection name for this tenant's knowledge base."""
        return f"kb_{self.slug}"

    @property
    def redis_prefix(self) -> str:
        """Redis key prefix for this tenant."""
        return self.slug

    @property
    def minio_bucket(self) -> str:
        """MinIO bucket name for this tenant's files."""
        return f"cri-{self.slug}"
