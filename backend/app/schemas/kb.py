"""Pydantic v2 schemas for Knowledge Base (KBDocument + KBChunk)."""

import uuid
from datetime import date, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.ingestion_errors import public_ingestion_error
from app.models.enums import KBDocumentStatus


class KBDocumentCreate(BaseModel):
    """Schema for creating a new KB document."""

    title: str = Field(..., min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=100)
    language: str = Field(default="fr", pattern=r"^(fr|ar|en)$")
    source_authority: str | None = Field(default=None, max_length=300)
    source_reference: str | None = Field(default=None, max_length=500)
    source_version: str | None = Field(default=None, max_length=100)
    published_at: date | None = None
    expires_at: date | None = None


class KBDocumentUpdate(BaseModel):
    """Schema for updating a KB document. All fields optional."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, pattern=r"^(fr|ar|en)$")
    status: KBDocumentStatus | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    source_authority: str | None = Field(default=None, max_length=300)
    source_reference: str | None = Field(default=None, max_length=500)
    source_version: str | None = Field(default=None, max_length=100)
    published_at: date | None = None
    expires_at: date | None = None


class KBDocumentValidationRequest(BaseModel):
    """Explicit human approval required before a document is indexed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_authority: str = Field(..., min_length=1, max_length=300)
    source_reference: str = Field(..., min_length=1, max_length=500)
    source_version: str = Field(..., min_length=1, max_length=100)
    published_at: date | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    expires_at: date | None = None

    @field_validator("source_url", mode="before")
    @classmethod
    def validate_source_url(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("URL de source invalide.")
        value = value.strip()
        if not value:
            return None
        if "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError("URL de source invalide.")
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("URL de source invalide.")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("URL de source invalide.") from exc
        return value


class KBDocumentResponse(BaseModel):
    """KB document response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_url: str | None
    source_authority: str | None
    source_reference: str | None
    source_version: str | None
    published_at: date | None
    verified_at: datetime | None
    expires_at: date | None
    validated_by: uuid.UUID | None
    validated_at: datetime | None
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

    @field_serializer("error_message")
    def serialize_error_message(self, message: str | None) -> str | None:
        """Legacy failures can contain provider details and must not be exposed."""
        return public_ingestion_error(message)


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
