"""Admin model — stored in the PUBLIC schema.

Back-office administrators. Scoped to a tenant via tenant_id,
or null for super_admin (cross-tenant access).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import AdminRole

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Admin(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "admins"
    __table_args__ = (
        Index("ix_admins_email", "email", unique=True),
        Index("ix_admins_tenant_id", "tenant_id"),
        Index("ix_admins_role", "role"),
        {"schema": "public"},
    )

    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="adminrole", schema="public"),
        nullable=False,
        default=AdminRole.viewer,
        server_default=AdminRole.viewer.value,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="SET NULL"),
        nullable=True,
        comment="Null for super_admin (cross-tenant access)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    tenant: Mapped[Tenant | None] = relationship()

    def __repr__(self) -> str:
        return f"<Admin email={self.email!r} role={self.role.value}>"
