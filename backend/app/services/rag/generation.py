"""GenerationService — full RAG generation pipeline.

Pipeline: detect language → retrieve chunks → anonymize → build prompt → Gemini → response.

Usage:
    service = get_generation_service()
    response = await service.generate(tenant, request)
"""

from __future__ import annotations

import time
import uuid

import structlog
from prometheus_client import Counter, Histogram

from app.core.exceptions import GenerationError
from app.core.tenant import TenantContext
from app.schemas.ai import GeminiRequest, GeminiResponse
from app.schemas.kb import KBDocumentValidationRequest
from app.schemas.rag import (
    ConversationTurn,
    GenerationRequest,
    GenerationResponse,
    RetrievalResult,
    RetrievedChunk,
)
from app.services.ai.gemini import get_gemini_service
from app.services.ai.language import get_language_service
from app.services.guardrails.pii_masker import get_pii_masker
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
        safe_query = self._anonymize_text(request.query)

        log = self._logger.bind(
            tenant=tenant.slug,
            trace_id=trace_id,
            query_length=len(request.query),
        )

        try:
            # 1. Detect language
            if request.language is None:
                lang_result = await self._language.detect(safe_query, tenant)
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
                    query=safe_query,
                    top_k=request.retrieval_top_k,
                    filters=request.retrieval_filters,
                    language=language,
                    confidence_threshold=request.confidence_threshold,
                    allow_language_fallback=True,
                )
                chunks = retrieval_result.chunks
                confidence = retrieval_result.confidence
                is_confident = retrieval_result.is_confident

            # 3. No chunks → early return with "no_answer"
            if not chunks:
                GENERATION_CONFIDENCE.labels(tenant=tenant.slug).observe(0.0)
                latency_ms = (time.monotonic() - start_time) * 1000
                GENERATION_REQUESTS.labels(
                    tenant=tenant.slug, status="no_chunks", language=language
                ).inc()
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

            # The public response can display at most three documents. Do not
            # give the model additional documents whose citations would be
            # silently dropped from the answer shown to the user.
            cited_documents = {source["document_id"] for source in self._build_sources(chunks)}
            selected_chunks = [chunk for chunk in chunks if chunk.document_id in cited_documents]
            if len(selected_chunks) != len(chunks):
                # A passage excluded from the prompt cannot support the answer
                # or increase confidence in it. Preserve any stricter upstream
                # confidence rather than making the answer more confident.
                confidence = min(confidence, self._compute_chunks_confidence(selected_chunks))
                is_confident = is_confident and confidence >= request.confidence_threshold
            chunks = selected_chunks
            GENERATION_CONFIDENCE.labels(tenant=tenant.slug).observe(confidence)

            # 4. Confidence check → disclaimer
            disclaimer: str | None = None
            if not is_confident:
                disclaimer = PromptTemplates.get_message("disclaimer", language)

            # 5. Anonymize chunks
            anonymized_chunks = self._anonymize_chunks(chunks)

            # 6. Build prompt
            history_turns = self._anonymize_history(
                self._truncate_history(request.conversation_history, request.max_history_turns)
            )
            context_prompt = PromptTemplates.build_context(
                chunks=anonymized_chunks,
                history=history_turns,
                query=safe_query,
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
            sources = self._build_sources(chunks)

            # Prepend disclaimer to answer if confidence is low
            answer = gemini_response.text
            if disclaimer:
                answer = f"{disclaimer}\n\n{answer}"

            GENERATION_REQUESTS.labels(
                tenant=tenant.slug, status="success", language=language
            ).inc()
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
                sources=sources,
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
        """Pseudonymize text before it is sent to any external AI service."""
        return get_pii_masker().mask(text).masked_text

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
                metadata={
                    **c.metadata,
                    "table_header": self._anonymize_text(c.metadata["table_header"])
                    if isinstance(c.metadata.get("table_header"), str)
                    else None,
                },
            )
            for c in chunks
        ]

    def _anonymize_history(self, history: list[ConversationTurn]) -> list[ConversationTurn]:
        """Return a PII-safe copy of locally retained conversation history."""
        return [
            ConversationTurn(role=turn.role, content=self._anonymize_text(turn.content))
            for turn in history
        ]

    @staticmethod
    def _safe_source_url(value: object) -> str | None:
        """Drop unsafe legacy URLs before returning citations to clients."""
        if not isinstance(value, str) or len(value) > 1000:
            return None
        try:
            return KBDocumentValidationRequest.validate_source_url(value)
        except ValueError:
            return None

    @staticmethod
    def _build_sources(chunks: list[RetrievedChunk]) -> list[dict]:
        """Create up to three stable, document-level citations for the user."""
        sources: list[dict] = []
        by_document: dict[str, dict] = {}
        for chunk in chunks:
            metadata = chunk.metadata
            pages = metadata.get("page_numbers")
            pages = (
                sorted({page for page in pages if type(page) is int and page > 0})
                if isinstance(pages, list)
                else []
            )
            if chunk.document_id in by_document:
                source = by_document[chunk.document_id]
                source["page_numbers"] = sorted(set(source["page_numbers"]) | set(pages))
                continue
            if len(sources) == 3:
                continue
            source = {
                "document_id": chunk.document_id,
                "title": metadata.get("title", "Document"),
                "authority": metadata.get("source_authority"),
                "reference": metadata.get("source_reference"),
                "version": metadata.get("source_version"),
                "published_at": metadata.get("published_at"),
                "url": GenerationService._safe_source_url(metadata.get("source_url")),
                "section_path": metadata.get("section_path") or [],
                "page_numbers": pages,
                "language": metadata.get("language") or None,
            }
            sources.append(source)
            by_document[chunk.document_id] = source
        return sources

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
