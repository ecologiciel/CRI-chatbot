"""InternalWhitelist model — stored in the TENANT schema.

Controls which phone numbers can access the Agent Interne feature.
Managed by admins via the back-office.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class InternalWhitelist(UUIDMixin, TimestampMixin, Base):
    """Phone number authorized for internal agent access.

    Each tenant maintains its own whitelist. A phone present here
    and marked ``is_active=True`` is routed to Agent Interne instead
    of the public FAQ agent.

    Attributes:
        phone: E.164 formatted phone number, unique per tenant.
        label: Optional display label (employee name or department).
        note: Free-text admin note about why this number was whitelisted.
        is_active: Soft-delete flag — ``False`` disables without removing.
        added_by: UUID of the admin who added this entry (FK to public.admins).
    """

    __tablename__ = "internal_whitelist"
    __table_args__ = (
        Index("ix_internal_whitelist_phone", "phone", unique=True),
        Index("ix_internal_whitelist_phone_active", "phone", "is_active"),
        Index("ix_internal_whitelist_added_by", "added_by"),
        Index("ix_internal_whitelist_is_active", "is_active"),
    )

    phone: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="E.164 format, e.g. +212612345678",
    )
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Optional display label (e.g. employee name or department)",
    )
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Admin note about why this number was whitelisted",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.admins.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<InternalWhitelist phone={self.phone!r} is_active={self.is_active}>"
