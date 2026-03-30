"""GeminiService — async Gemini 2.5 Flash client with retry, cost tracking, and metrics.

Usage:
    service = get_gemini_service()
    response = await service.generate(request, tenant)
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

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
from app.core.exceptions import GeminiError
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.schemas.ai import CostSnapshot, GeminiRequest, GeminiResponse

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
GEMINI_REQUESTS = Counter(
    "cri_gemini_requests_total",
    "Total Gemini API requests",
    ["model", "status"],
)
GEMINI_TOKENS = Counter(
    "cri_gemini_tokens_total",
    "Total tokens consumed by Gemini",
    ["model", "direction"],
)
GEMINI_LATENCY = Histogram(
    "cri_gemini_latency_seconds",
    "Gemini API call latency in seconds",
    ["model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ---------------------------------------------------------------------------
# Retryable exceptions from the Google API
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
    # Fallback: retry on any Exception (less precise, but safe)
    _RETRYABLE_EXCEPTIONS = (Exception,)


def _log_retry(retry_state: object) -> None:
    """Log retry attempts via structlog."""
    logger.warning(
        "gemini_retry",
        attempt=getattr(retry_state, "attempt_number", "?"),
    )


class GeminiService:
    """Async Gemini 2.5 Flash client with retry, cost tracking, and metrics.

    Thread-safe, async-only. Created once at startup, shared across requests.
    All calls are tenant-scoped for cost tracking.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._temperature = settings.gemini_temperature
        self._logger = logger.bind(service="gemini")

    async def generate(
        self,
        request: GeminiRequest,
        tenant: TenantContext,
    ) -> GeminiResponse:
        """Generate text using Gemini 2.5 Flash.

        Args:
            request: Generation request (contents must be pre-anonymized).
            tenant: Current tenant context for cost tracking.

        Returns:
            GeminiResponse with generated text, token counts, and latency.

        Raises:
            GeminiError: If all retries are exhausted.
        """
        trace_id = request.trace_id or str(uuid.uuid4())
        start_time = time.monotonic()

        try:
            return await self._generate_with_retry(request, tenant, trace_id, start_time)
        except GeminiError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            GEMINI_REQUESTS.labels(model=self._model, status="error").inc()
            self._logger.error(
                "gemini_error",
                trace_id=trace_id,
                error=str(exc),
                latency_ms=round(latency_ms, 1),
                tenant=tenant.slug,
            )
            raise GeminiError(
                message=f"Gemini generation failed: {exc}",
                details={"model": self._model, "trace_id": trace_id},
            ) from exc

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _generate_with_retry(
        self,
        request: GeminiRequest,
        tenant: TenantContext,
        trace_id: str,
        start_time: float,
    ) -> GeminiResponse:
        """Internal method with tenacity retry. Raises raw SDK exceptions."""
        config = types.GenerateContentConfig(
            system_instruction=request.system_instruction,
            temperature=request.temperature
            if request.temperature is not None
            else self._temperature,
            max_output_tokens=request.max_output_tokens or self._max_output_tokens,
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=request.contents,
            config=config,
        )

        latency_ms = (time.monotonic() - start_time) * 1000

        # Extract token counts
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0
        content = response.text or ""
        finish_reason = (
            response.candidates[0].finish_reason.name
            if response.candidates and response.candidates[0].finish_reason
            else None
        )

        # Prometheus metrics
        GEMINI_REQUESTS.labels(model=self._model, status="success").inc()
        GEMINI_TOKENS.labels(model=self._model, direction="input").inc(input_tokens)
        GEMINI_TOKENS.labels(model=self._model, direction="output").inc(output_tokens)
        GEMINI_LATENCY.labels(model=self._model).observe(latency_ms / 1000)

        # Cost tracking per tenant in Redis
        await self._track_cost(tenant, input_tokens, output_tokens)

        # Structured log — NO PII, NO prompt content, NO response text
        self._logger.info(
            "gemini_generate",
            trace_id=trace_id,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(latency_ms, 1),
            finish_reason=finish_reason,
            tenant=tenant.slug,
        )

        return GeminiResponse(
            text=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model=self._model,
            latency_ms=round(latency_ms, 1),
            finish_reason=finish_reason,
        )

    async def generate_simple(
        self,
        prompt: str,
        tenant: TenantContext,
        system_prompt: str | None = None,
    ) -> str:
        """Shortcut for simple single-turn generation. Returns text content only."""
        request = GeminiRequest(
            contents=prompt,
            system_instruction=system_prompt,
        )
        response = await self.generate(request, tenant)
        return response.text

    async def classify_intent(self, text: str, tenant: TenantContext) -> str:
        """Quick intent classification (~50 tokens). Returns lowercase intent label.

        Possible labels: faq, incitations, suivi_dossier, interne,
        escalade, hors_perimetre, salutation.
        """
        system = (
            "Tu es un classificateur d'intention. Réponds UNIQUEMENT par un mot parmi: "
            "faq, incitations, suivi_dossier, interne, escalade, hors_perimetre, salutation"
        )
        request = GeminiRequest(
            contents=text,
            system_instruction=system,
            max_output_tokens=20,
            temperature=0.0,
        )
        response = await self.generate(request, tenant)
        return response.text.strip().lower()

    async def get_tenant_usage(
        self,
        tenant: TenantContext,
        month: str | None = None,
    ) -> CostSnapshot:
        """Get AI token usage for a tenant for a given month.

        Args:
            tenant: Tenant context.
            month: YYYY-MM string. Defaults to current month.

        Returns:
            CostSnapshot with token counts and request count.
        """
        month = month or datetime.now(UTC).strftime("%Y-%m")
        redis = get_redis()
        redis_key = f"{tenant.redis_prefix}:ai:costs:{month}"
        data = await redis.hgetall(redis_key)
        return CostSnapshot(
            tenant_slug=tenant.slug,
            month=month,
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            embedding_tokens=int(data.get("embedding_tokens", 0)),
            request_count=int(data.get("request_count", 0)),
        )

    async def _track_cost(
        self,
        tenant: TenantContext,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Track token usage per tenant per month in Redis."""
        redis = get_redis()
        month_key = f"{tenant.redis_prefix}:ai:costs:{datetime.now(UTC).strftime('%Y-%m')}"
        pipe = redis.pipeline()
        pipe.hincrby(month_key, "input_tokens", input_tokens)
        pipe.hincrby(month_key, "output_tokens", output_tokens)
        pipe.hincrby(month_key, "request_count", 1)
        pipe.expire(month_key, 90 * 86400)  # 90-day TTL
        await pipe.execute()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_gemini_service: GeminiService | None = None


def get_gemini_service() -> GeminiService:
    """Get or create the GeminiService singleton."""
    global _gemini_service  # noqa: PLW0603
    if _gemini_service is None:
        _gemini_service = GeminiService(get_settings())
    return _gemini_service
