"""Base models and mixins for all SQLAlchemy models.

All models MUST inherit from Base and use the appropriate mixins.
Convention: UUIDMixin + TimestampMixin for ALL tables.

Usage:
    class Tenant(UUIDMixin, TimestampMixin, Base):
        __tablename__ = "tenants"
        __table_args__ = {"schema": "public"}
        name: Mapped[str] = mapped_column(String(255))
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDMixin:
    """Provides a UUID primary key.

    Uses gen_random_uuid() server-side (native PostgreSQL 13+).
    Python-side default via uuid4 for pre-flush access.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    """Provides created_at and updated_at timestamps.

    Note: onupdate=func.now() is ORM-only. Raw SQL UPDATEs
    won't trigger it — add a DB trigger if needed later.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
