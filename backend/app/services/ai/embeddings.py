"""EmbeddingService — text embedding via Google text-embedding-004 with batch support.

Usage:
    service = get_embedding_service()
    response = await service.embed(request, tenant)
    vector = await service.embed_single("query text", tenant)
"""

from __future__ import annotations

import time

import structlog
from google import genai
from google.genai import types
from prometheus_client import Counter, Histogram
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings, get_settings
from app.core.exceptions import EmbeddingError
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.schemas.ai import EmbeddingRequest, EmbeddingResponse

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
EMBEDDING_REQUESTS = Counter(
    "cri_embedding_requests_total",
    "Total embedding API requests",
    ["tenant", "model", "status"],
)
EMBEDDING_TOKENS = Counter(
    "cri_embedding_tokens_total",
    "Total tokens processed for embeddings",
    ["tenant", "model"],
)
EMBEDDING_LATENCY = Histogram(
    "cri_embedding_latency_seconds",
    "Embedding API call latency in seconds",
    ["tenant", "model"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# ---------------------------------------------------------------------------
# Retryable exceptions (shared logic with gemini.py)
# ---------------------------------------------------------------------------
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = ()
try:
    from google.api_core.exceptions import (
        DeadlineExceeded,
        InternalServerError,
        ResourceExhausted,
        ServiceUnavailable,
    )

    _RETRYABLE_EXCEPTIONS = (
        ResourceExhausted,
        ServiceUnavailable,
        DeadlineExceeded,
        InternalServerError,
    )
except ImportError:
    _RETRYABLE_EXCEPTIONS = (Exception,)


def _log_retry(retry_state: object) -> None:
    """Log retry attempts via structlog."""
    logger.warning(
        "embedding_retry",
        attempt=getattr(retry_state, "attempt_number", "?"),
    )


class EmbeddingService:
    """Generate embeddings via Google text-embedding-004.

    Supports batched embedding with automatic chunking when the input
    exceeds the configured batch size.

    Thread-safe, async-only. Created once at startup, shared across requests.
    """

    # TODO Phase 2: Local fallback via sentence-transformers + multilingual-e5-large

    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.embedding_model
        self._dimension = settings.embedding_dimension
        self._batch_size = settings.embedding_batch_size
        self._logger = logger.bind(service="embeddings")

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _embed_batch_internal(
        self,
        texts: list[str],
        task_type: str,
    ) -> tuple[list[list[float]], int]:
        """Embed a single batch (≤ batch_size texts). Returns (vectors, token_count).

        This is the low-level method with retry logic. Callers should use
        embed() or embed_batch() instead.
        """
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._dimension,
        )

        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=texts,
            config=config,
        )

        vectors = [emb.values for emb in result.embeddings]

        # Token count: use API metadata if available, else approximate
        token_count = 0
        if hasattr(result, "usage_metadata") and result.usage_metadata:
            token_count = getattr(result.usage_metadata, "prompt_token_count", 0) or 0
        if token_count == 0:
            # Rough approximation: ~1.3 tokens per word
            token_count = sum(len(t.split()) for t in texts)

        return vectors, token_count

    async def embed(
        self,
        request: EmbeddingRequest,
        tenant: TenantContext,
    ) -> EmbeddingResponse:
        """Generate embeddings for a list of texts.

        Automatically splits into sub-batches if len(texts) > batch_size.

        Args:
            request: Embedding request with texts and task_type.
            tenant: Current tenant context for cost tracking.

        Returns:
            EmbeddingResponse with embedding vectors and metadata.

        Raises:
            EmbeddingError: If the embedding API call fails.
        """
        start_time = time.monotonic()
        all_vectors: list[list[float]] = []
        total_tokens = 0

        try:
            # Split into sub-batches
            for i in range(0, len(request.texts), self._batch_size):
                batch = request.texts[i : i + self._batch_size]
                vectors, tokens = await self._embed_batch_internal(batch, request.task_type)
                all_vectors.extend(vectors)
                total_tokens += tokens

            latency_ms = (time.monotonic() - start_time) * 1000

            # Prometheus metrics
            EMBEDDING_REQUESTS.labels(tenant=tenant.slug, model=self._model, status="success").inc()
            EMBEDDING_TOKENS.labels(tenant=tenant.slug, model=self._model).inc(total_tokens)
            EMBEDDING_LATENCY.labels(tenant=tenant.slug, model=self._model).observe(latency_ms / 1000)

            # Cost tracking per tenant in Redis
            await self._track_cost(tenant, total_tokens)

            self._logger.info(
                "embeddings_generated",
                trace_id=request.trace_id,
                model=self._model,
                text_count=len(request.texts),
                total_tokens=total_tokens,
                latency_ms=round(latency_ms, 1),
                tenant=tenant.slug,
            )

            return EmbeddingResponse(
                embeddings=all_vectors,
                model=self._model,
                dimension=self._dimension,
                total_tokens=total_tokens,
                latency_ms=round(latency_ms, 1),
            )

        except EmbeddingError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            EMBEDDING_REQUESTS.labels(tenant=tenant.slug, model=self._model, status="error").inc()
            self._logger.error(
                "embedding_error",
                trace_id=request.trace_id,
                model=self._model,
                error=str(exc),
                latency_ms=round(latency_ms, 1),
                tenant=tenant.slug,
            )
            raise EmbeddingError(
                message=f"Embedding generation failed: {exc}",
                details={"model": self._model},
            ) from exc

    async def embed_single(
        self,
        text: str,
        tenant: TenantContext,
        task_type: str = "RETRIEVAL_QUERY",
    ) -> list[float]:
        """Embed a single text. Returns the embedding vector directly.

        Defaults to RETRIEVAL_QUERY task_type (optimized for search queries).
        """
        request = EmbeddingRequest(texts=[text], task_type=task_type)
        response = await self.embed(request, tenant)
        return response.embeddings[0]

    async def embed_batch(
        self,
        texts: list[str],
        tenant: TenantContext,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """Embed a large collection of texts. Returns list of vectors.

        Handles automatic batching. Defaults to RETRIEVAL_DOCUMENT
        task_type (optimized for indexing).
        """
        request = EmbeddingRequest(texts=texts, task_type=task_type)
        response = await self.embed(request, tenant)
        return response.embeddings

    async def _track_cost(self, tenant: TenantContext, tokens: int) -> None:
        """Track embedding token usage per tenant per month in Redis."""
        from datetime import UTC, datetime

        redis = get_redis()
        month_key = f"{tenant.redis_prefix}:ai:costs:{datetime.now(UTC).strftime('%Y-%m')}"
        pipe = redis.pipeline()
        pipe.hincrby(month_key, "embedding_tokens", tokens)
        pipe.hincrby(month_key, "request_count", 1)
        pipe.expire(month_key, 90 * 86400)  # 90-day TTL
        await pipe.execute()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the EmbeddingService singleton."""
    global _embedding_service  # noqa: PLW0603
    if _embedding_service is None:
        _embedding_service = EmbeddingService(get_settings())
    return _embedding_service
