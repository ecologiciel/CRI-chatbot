"""Pydantic v2 schemas for Knowledge Base (KBDocument + KBChunk)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import KBDocumentStatus


class KBDocumentCreate(BaseModel):
    """Schema for creating a new KB document."""

    title: str = Field(..., min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=100)
    language: str = Field(default="fr", pattern=r"^(fr|ar|en)$")


class KBDocumentUpdate(BaseModel):
    """Schema for updating a KB document. All fields optional."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, pattern=r"^(fr|ar|en)$")
    status: KBDocumentStatus | None = None


class KBDocumentResponse(BaseModel):
    """KB document response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_url: str | None
    category: str | None
    language: str
    content_hash: str | None
    file_path: str | None
    file_size: int | None
    chunk_count: int
    status: KBDocumentStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class KBChunkResponse(BaseModel):
    """KB chunk response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    content: str
    chunk_index: int
    qdrant_point_id: str | None
    token_count: int | None
    created_at: datetime


class KBDocumentDetailResponse(KBDocumentResponse):
    """KB document with its chunks — for detail views."""

    chunks: list[KBChunkResponse] = Field(default_factory=list)


class KBDocumentList(BaseModel):
    """Paginated list of KB documents."""

    items: list[KBDocumentResponse]
    total: int
    page: int
    page_size: int
