"""Durable import requests, staged separately from the Redis wake-up queue."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class DossierImportRequest(UUIDMixin, Base):
    __tablename__ = "dossier_import_requests"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'processing', 'completed', 'failed', 'uncertain')",
            name="ck_dossier_import_request_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_dossier_import_request_attempts"),
        CheckConstraint(
            "(review_state IN ('open', 'follow_up') AND review_outcome IS NULL) OR "
            "(review_state = 'closed' AND review_outcome IS NOT NULL AND review_outcome IN ('applied', 'not_applied'))",
            name="ck_dossier_import_request_review",
        ),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_dossier_import_request_lease",
        ),
        Index("uq_dossier_import_request_object", "tenant_id", "object_key", unique=True),
        Index(
            "uq_dossier_import_active_content",
            "tenant_id",
            "content_sha256",
            unique=True,
            postgresql_where=text("state <> 'failed'"),
        ),
        Index("ix_dossier_import_request_queue", "tenant_id", "state", "created_at"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    review_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
