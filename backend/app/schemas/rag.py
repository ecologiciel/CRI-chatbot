"""RAG pipeline schemas — internal DTOs and Gemini response models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Internal DTOs (frozen dataclasses — no validation overhead)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """Output of the chunking algorithm for a single chunk."""

    content: str
    chunk_index: int
    token_count: int
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A single chunk returned from Qdrant search with its similarity score."""

    chunk_id: str  # qdrant_point_id (UUID string)
    document_id: str  # from Qdrant payload (UUID string)
    content: str  # from Qdrant payload
    score: float  # cosine similarity score [0, 1]
    metadata: dict = field(default_factory=dict)  # from Qdrant payload


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Complete retrieval result with confidence scoring."""

    chunks: list[RetrievedChunk]
    confidence: float  # avg of top-3 scores [0.0, 1.0]
    query_embedding: list[float]
    total_results: int
    is_confident: bool  # confidence >= threshold (default 0.7)


# ---------------------------------------------------------------------------
# Pydantic model for Gemini structured output parsing
# ---------------------------------------------------------------------------


class MetadataEnrichment(BaseModel):
    """Structured metadata extracted by Gemini from chunk content.

    Used to parse JSON responses from Gemini during metadata enrichment.
    All fields have defaults so partial/malformed responses degrade gracefully.
    """

    related_laws: list[str] = Field(default_factory=list)
    applicable_sectors: list[str] = Field(default_factory=list)
    legal_forms: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    language: str = Field(default="fr")
    summary: str = Field(default="")


# ---------------------------------------------------------------------------
# Conversation DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A single exchange in conversation history."""

    role: str  # "user" or "assistant"
    content: str


# ---------------------------------------------------------------------------
# Generation request / response (Pydantic — used at API boundary)
# ---------------------------------------------------------------------------


class GenerationRequest(BaseModel):
    """Input for the RAG generation pipeline."""

    query: str = Field(..., min_length=1, max_length=5000)
    language: str | None = Field(
        default=None,
        description="fr/ar/en — auto-detected from query if None",
    )
    conversation_history: list[dict] = Field(
        default_factory=list,
        description='[{"role": "user"|"assistant", "content": "..."}]',
    )
    max_history_turns: int = Field(default=5, ge=0, le=20)
    chunks: list | None = Field(
        default=None,
        description="Pre-retrieved RetrievedChunk list — skips retrieval when provided",
    )
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    retrieval_filters: dict | None = None
    trace_id: str | None = None


class GenerationResponse(BaseModel):
    """Output from the RAG generation pipeline."""

    answer: str
    language: str
    chunk_ids: list[str] = Field(default_factory=list)
    confidence: float
    is_confident: bool
    disclaimer: str | None = None
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    trace_id: str | None = None
