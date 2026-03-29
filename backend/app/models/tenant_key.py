"""Tenant encryption key model (envelope encryption).

Each tenant has one active AES-256-GCM data key, encrypted by the
platform master key before storage. Supports key rotation via the
is_active flag and key_version counter.

Table lives in the PUBLIC schema (alongside tenants).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class TenantKey(UUIDMixin, Base):
    """Per-tenant encryption key for envelope encryption.

    The encrypted_key column stores the tenant's AES-256 data key,
    itself encrypted by the platform master key (KMS_MASTER_KEY env var).
    Format: nonce (12 bytes) + ciphertext + GCM tag (16 bytes).

    Attributes:
        tenant_id: FK to public.tenants — one active key per tenant.
        encrypted_key: BYTEA blob containing the wrapped data key.
        algorithm: Encryption algorithm identifier.
        key_version: Incremented on each rotation.
        is_active: Only one active key per tenant (partial unique index).
        created_at: When this key was generated.
        rotated_at: When this key was superseded by a newer version.
    """

    __tablename__ = "tenant_keys"
    __table_args__ = (
        Index(
            "ix_tenant_keys_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active = TRUE"),
        ),
        Index("ix_tenant_keys_tenant", "tenant_id"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    encrypted_key: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Wrapped data key: nonce(12) + ciphertext + tag(16)",
    )
    algorithm: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="AES-256-GCM",
        server_default="AES-256-GCM",
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
