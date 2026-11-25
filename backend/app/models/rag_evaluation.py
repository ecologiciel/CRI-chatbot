"""Tenant-scoped RAG evaluation cases and aggregate monitoring runs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class RAGEvaluationCase(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_cases"
    __table_args__ = (Index("ix_rag_evaluation_cases_active", "is_active"),)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, server_default="fr")
    expected_document_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    expects_abstention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    human_faithfulness: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class RAGEvaluationRun(UUIDMixin, Base):
    __tablename__ = "rag_evaluation_runs"
    __table_args__ = (Index("ix_rag_evaluation_runs_created_at", "created_at"),)

    case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'::jsonb")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
