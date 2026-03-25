"""Knowledge Base models — stored in the TENANT schema.

KBDocument = a crawled page or uploaded file.
KBChunk = a chunk of a document, embedded and stored in Qdrant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import KBDocumentStatus


class KBDocument(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        Index("ix_kb_documents_category", "category"),
        Index("ix_kb_documents_status", "status"),
        Index("ix_kb_documents_content_hash", "content_hash"),
        Index("ix_kb_documents_created_at", "created_at"),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="fr",
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="SHA-256 for dedup",
    )
    file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="MinIO path",
    )
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    status: Mapped[KBDocumentStatus] = mapped_column(
        Enum(KBDocumentStatus, name="kbdocumentstatus", schema="public"),
        nullable=False,
        default=KBDocumentStatus.pending,
        server_default=KBDocumentStatus.pending.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, default=None,
    )

    # Relationships
    chunks: Mapped[list[KBChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KBDocument title={self.title!r} status={self.status.value}>"


class KBChunk(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_doc_index"),
        Index("ix_kb_chunks_document_id", "document_id"),
        Index("ix_kb_chunks_qdrant_point_id", "qdrant_point_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    qdrant_point_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Qdrant vector point ID",
    )
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, default=None,
    )

    # Relationships
    document: Mapped[KBDocument] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<KBChunk doc={self.document_id} index={self.chunk_index}>"
