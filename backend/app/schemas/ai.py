"""Pydantic v2 schemas for AI services (Gemini generation + embeddings)."""

from pydantic import BaseModel, Field


class GeminiRequest(BaseModel):
    """Input schema for GeminiService.generate().

    The `contents` field should contain the full prompt text,
    already anonymized by the caller (no PII).
    """

    contents: str = Field(..., min_length=1, description="Prompt text (already anonymized)")
    system_instruction: str | None = Field(
        default=None, description="System-level instruction"
    )
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Override default temperature"
    )
    max_output_tokens: int | None = Field(
        default=None, gt=0, description="Override default max output tokens"
    )
    trace_id: str | None = Field(
        default=None, description="Correlation ID for log tracing"
    )


class GeminiResponse(BaseModel):
    """Output schema from GeminiService.generate()."""

    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    latency_ms: float
    finish_reason: str | None = None


class EmbeddingRequest(BaseModel):
    """Input schema for EmbeddingService.embed().

    Texts are embedded in a single API call (max batch_size per call).
    For larger collections, use EmbeddingService.embed_batch().
    """

    texts: list[str] = Field(..., min_length=1, description="Texts to embed")
    task_type: str = Field(
        default="RETRIEVAL_DOCUMENT",
        description="RETRIEVAL_DOCUMENT (indexing) or RETRIEVAL_QUERY (search)",
    )
    trace_id: str | None = Field(
        default=None, description="Correlation ID for log tracing"
    )


class EmbeddingResponse(BaseModel):
    """Output schema from EmbeddingService.embed()."""

    embeddings: list[list[float]]
    model: str
    dimension: int
    total_tokens: int
    latency_ms: float


class CostSnapshot(BaseModel):
    """Per-tenant AI cost data for a given month."""

    tenant_slug: str
    month: str = Field(..., description="YYYY-MM format")
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    request_count: int = 0
