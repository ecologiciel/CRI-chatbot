"""GenerationService — full RAG generation pipeline.

Pipeline: detect language → retrieve chunks → anonymize → build prompt → Gemini → response.

Usage:
    service = get_generation_service()
    response = await service.generate(tenant, request)
"""

from __future__ import annotations

import re
import time
import uuid

import structlog
from prometheus_client import Counter, Histogram

from app.core.exceptions import GenerationError
from app.core.tenant import TenantContext
from app.schemas.ai import GeminiRequest, GeminiResponse
from app.schemas.rag import (
    ConversationTurn,
    GenerationRequest,
    GenerationResponse,
    RetrievalResult,
    RetrievedChunk,
)
from app.services.ai.gemini import get_gemini_service
from app.services.ai.language import get_language_service
from app.services.rag.prompts import PromptTemplates
from app.services.rag.retrieval import get_retrieval_service

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
GENERATION_REQUESTS = Counter(
    "cri_generation_requests_total",
    "RAG generation requests processed",
    ["tenant", "status", "language"],
)
GENERATION_LATENCY = Histogram(
    "cri_generation_latency_seconds",
    "RAG generation pipeline latency",
    ["tenant"],
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0],
)
GENERATION_CONFIDENCE = Histogram(
    "cri_generation_confidence",
    "Retrieval confidence for generation requests",
    ["tenant"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ---------------------------------------------------------------------------
# Compiled PII patterns (Moroccan-specific per CLAUDE.md §5.2)
# ---------------------------------------------------------------------------
_PII_CIN = re.compile(r"\b[A-Z]{1,2}\d{5,6}\b")
_PII_PHONE = re.compile(r"(?:\+212|0)[567][\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}")
_PII_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PII_AMOUNT = re.compile(
    r"\b\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{1,2})?\s*(?:MAD|DH|dirhams?)\b",
    re.IGNORECASE,
)


class GenerationService:
    """Full RAG generation: retrieve → anonymize → prompt → Gemini → response.

    Orchestrates the complete read path for the RAG pipeline. Each operation
    targets the tenant's isolated resources (Qdrant collection, Redis prefix).

    PII anonymization lives here temporarily; it will migrate to
    ``services/guardrails/`` in Phase 2.
    """

    def __init__(self) -> None:
        self._retrieval = get_retrieval_service()
        self._gemini = get_gemini_service()
        self._language = get_language_service()
        self._logger = logger.bind(service="generation")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        tenant: TenantContext,
        request: GenerationRequest,
    ) -> GenerationResponse:
        """Execute the full RAG generation pipeline.

        Steps:
            1. Detect language if not provided.
            2. Retrieve relevant chunks (or use pre-provided ones).
            3. Early return with ``no_answer`` if no chunks found.
            4. Check confidence — add disclaimer if below threshold.
            5. Anonymize chunk contents (PII removal before Gemini).
            6. Build prompt via PromptTemplates.
            7. Call Gemini 2.5 Flash.
            8. Return GenerationResponse with chunk_ids for feedback.

        Args:
            tenant: Current tenant context.
            request: Generation request parameters.

        Returns:
            GenerationResponse with answer, chunk_ids, confidence, etc.

        Raises:
            GenerationError: If the pipeline fails.
        """
        trace_id = request.trace_id or str(uuid.uuid4())
        start_time = time.monotonic()
        language = request.language or "fr"

        log = self._logger.bind(
            tenant=tenant.slug,
            trace_id=trace_id,
            query_length=len(request.query),
        )

        try:
            # 1. Detect language
            if request.language is None:
                lang_result = await self._language.detect(request.query, tenant)
                language = lang_result.language.value
                log = log.bind(language=language, lang_method=lang_result.method)

            # 2. Retrieve or use pre-provided chunks
            if request.chunks is not None:
                chunks = request.chunks
                confidence = self._compute_chunks_confidence(chunks)
                is_confident = confidence >= request.confidence_threshold
            else:
                retrieval_result: RetrievalResult = await self._retrieval.retrieve(
                    tenant=tenant,
                    query=request.query,
                    top_k=request.retrieval_top_k,
                    filters=request.retrieval_filters,
                    language=language,
                    confidence_threshold=request.confidence_threshold,
                )
                chunks = retrieval_result.chunks
                confidence = retrieval_result.confidence
                is_confident = retrieval_result.is_confident

            GENERATION_CONFIDENCE.labels(tenant=tenant.slug).observe(confidence)

            # 3. No chunks → early return with "no_answer"
            if not chunks:
                latency_ms = (time.monotonic() - start_time) * 1000
                GENERATION_REQUESTS.labels(tenant=tenant.slug, status="no_chunks", language=language).inc()
                log.info("generation_no_chunks", latency_ms=round(latency_ms, 1))
                return GenerationResponse(
                    answer=PromptTemplates.get_message("no_answer", language),
                    language=language,
                    chunk_ids=[],
                    confidence=0.0,
                    is_confident=False,
                    disclaimer=None,
                    model="none",
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    latency_ms=round(latency_ms, 1),
                    trace_id=trace_id,
                )

            # 4. Confidence check → disclaimer
            disclaimer: str | None = None
            if not is_confident:
                disclaimer = PromptTemplates.get_message("disclaimer", language)

            # 5. Anonymize chunks
            anonymized_chunks = self._anonymize_chunks(chunks)

            # 6. Build prompt
            history_turns = self._truncate_history(
                request.conversation_history, request.max_history_turns
            )
            context_prompt = PromptTemplates.build_context(
                chunks=anonymized_chunks,
                history=history_turns,
                query=request.query,
                language=language,
            )
            system_prompt = PromptTemplates.get_system_prompt(language)

            # 7. Call Gemini
            gemini_request = GeminiRequest(
                contents=context_prompt,
                system_instruction=system_prompt,
                temperature=0.3,
                trace_id=trace_id,
            )
            gemini_response: GeminiResponse = await self._gemini.generate(gemini_request, tenant)

            # 8. Build response
            latency_ms = (time.monotonic() - start_time) * 1000
            chunk_ids = self._extract_chunk_ids(chunks)

            # Prepend disclaimer to answer if confidence is low
            answer = gemini_response.text
            if disclaimer:
                answer = f"{disclaimer}\n\n{answer}"

            GENERATION_REQUESTS.labels(tenant=tenant.slug, status="success", language=language).inc()
            GENERATION_LATENCY.labels(tenant=tenant.slug).observe(latency_ms / 1000)

            log.info(
                "generation_success",
                language=language,
                confidence=round(confidence, 3),
                is_confident=is_confident,
                chunks_used=len(chunks),
                input_tokens=gemini_response.input_tokens,
                output_tokens=gemini_response.output_tokens,
                latency_ms=round(latency_ms, 1),
            )

            return GenerationResponse(
                answer=answer,
                language=language,
                chunk_ids=chunk_ids,
                confidence=confidence,
                is_confident=is_confident,
                disclaimer=disclaimer,
                model=gemini_response.model,
                input_tokens=gemini_response.input_tokens,
                output_tokens=gemini_response.output_tokens,
                total_tokens=gemini_response.total_tokens,
                latency_ms=round(latency_ms, 1),
                trace_id=trace_id,
            )

        except GenerationError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            GENERATION_REQUESTS.labels(tenant=tenant.slug, status="error", language=language).inc()
            log.error(
                "generation_error",
                error=str(exc),
                latency_ms=round(latency_ms, 1),
            )
            raise GenerationError(
                message=f"RAG generation failed: {exc}",
                details={"trace_id": trace_id, "tenant": tenant.slug},
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _anonymize_text(self, text: str) -> str:
        """Remove PII from text before sending to Gemini.

        Patterns are Moroccan-specific per CLAUDE.md §5.2:
        - CIN (national ID): [A-Z]{1,2}\\d{5,6}
        - Phone: +212/06/07 formats
        - Email addresses
        - Amounts in MAD/DH/dirhams
        """
        text = _PII_CIN.sub("[CIN]", text)
        text = _PII_PHONE.sub("[TELEPHONE]", text)
        text = _PII_EMAIL.sub("[EMAIL]", text)
        text = _PII_AMOUNT.sub("[MONTANT]", text)
        return text

    def _anonymize_chunks(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Create new RetrievedChunk instances with anonymized content.

        Frozen dataclasses cannot be mutated — we reconstruct them.
        """
        return [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                content=self._anonymize_text(c.content),
                score=c.score,
                metadata=c.metadata,
            )
            for c in chunks
        ]

    @staticmethod
    def _truncate_history(
        history: list[dict],
        max_turns: int,
    ) -> list[ConversationTurn]:
        """Convert raw history dicts to ConversationTurn and keep last N turns."""
        turns = [
            ConversationTurn(role=h.get("role", "user"), content=h.get("content", ""))
            for h in history
        ]
        return turns[-max_turns:] if max_turns > 0 else []

    @staticmethod
    def _extract_chunk_ids(chunks: list[RetrievedChunk]) -> list[str]:
        """Extract chunk_ids from RetrievedChunk list for feedback correlation."""
        return [c.chunk_id for c in chunks]

    @staticmethod
    def _compute_chunks_confidence(chunks: list[RetrievedChunk]) -> float:
        """Compute confidence from pre-retrieved chunks (avg of top-3 scores).

        Mirrors the formula in RetrievalService._compute_confidence().
        """
        if not chunks:
            return 0.0
        top_scores = sorted((c.score for c in chunks), reverse=True)[:3]
        return sum(top_scores) / len(top_scores)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_generation_service: GenerationService | None = None


def get_generation_service() -> GenerationService:
    """Get or create the GenerationService singleton."""
    global _generation_service  # noqa: PLW0603
    if _generation_service is None:
        _generation_service = GenerationService()
    return _generation_service
