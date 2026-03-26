"""RetrievalService — query → embed → Qdrant search → confidence scoring.

Usage:
    service = get_retrieval_service()
    result = await service.retrieve(tenant, "Quelles sont les incitations fiscales?")
"""

from __future__ import annotations

import time

import structlog
from prometheus_client import Counter, Histogram
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)

from app.core.exceptions import RetrievalError
from app.core.qdrant import get_qdrant
from app.core.tenant import TenantContext
from app.schemas.rag import RetrievalResult, RetrievedChunk
from app.services.ai.embeddings import get_embedding_service

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
RETRIEVAL_REQUESTS = Counter(
    "cri_retrieval_requests_total",
    "Retrieval requests processed",
    ["status"],
)
RETRIEVAL_LATENCY = Histogram(
    "cri_retrieval_latency_seconds",
    "Retrieval pipeline latency",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
RETRIEVAL_CONFIDENCE = Histogram(
    "cri_retrieval_confidence",
    "Retrieval confidence score distribution",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# Defaults (per CLAUDE.md §6.2)
DEFAULT_TOP_K = 5
CONFIDENCE_THRESHOLD = 0.7

# Fields that support MatchAny (array containment) filtering
_MATCH_ANY_FIELDS = {"applicable_sectors", "legal_forms", "related_laws", "regions"}


class RetrievalService:
    """Query-time retrieval: embed query → Qdrant search → confidence scoring.

    All searches target the tenant's isolated Qdrant collection (kb_{slug}).
    """

    def __init__(self) -> None:
        self._embedder = get_embedding_service()
        self._qdrant = get_qdrant()
        self._logger = logger.bind(service="retrieval")

    async def retrieve(
        self,
        tenant: TenantContext,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        filters: dict | None = None,
        language: str | None = None,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> RetrievalResult:
        """Retrieve relevant chunks for a query.

        Args:
            tenant: Tenant context (determines Qdrant collection).
            query: User query text.
            top_k: Number of results to return (default 5).
            filters: Optional metadata filters:
                - applicable_sectors: list[str] — match any
                - legal_forms: list[str] — match any
                - related_laws: list[str] — match any
                - regions: list[str] — match any
            language: Optional language filter (exact match: fr/ar/en).
            confidence_threshold: Minimum confidence for is_confident flag.

        Returns:
            RetrievalResult with chunks, confidence, and metadata.

        Raises:
            RetrievalError: If embedding or search fails.
        """
        start_time = time.monotonic()
        log = self._logger.bind(
            tenant=tenant.slug,
            query_length=len(query),
            top_k=top_k,
        )

        try:
            # 1. Embed the query
            query_embedding = await self._embedder.embed_single(
                query, tenant, task_type="RETRIEVAL_QUERY",
            )

            # 2. Build Qdrant filter
            qdrant_filter = self._build_qdrant_filter(filters, language)

            # 3. Search Qdrant
            results = await self._qdrant.search(
                collection_name=tenant.qdrant_collection,
                query_vector=query_embedding,
                limit=top_k,
                query_filter=qdrant_filter,
                with_payload=True,
                score_threshold=0.0,  # Return all, let confidence decide
            )

            # 4. Map to RetrievedChunk
            chunks: list[RetrievedChunk] = []
            for point in results:
                payload = point.payload or {}
                chunks.append(RetrievedChunk(
                    chunk_id=str(point.id),
                    document_id=payload.get("document_id", ""),
                    content=payload.get("content", ""),
                    score=point.score,
                    metadata={
                        "title": payload.get("title", ""),
                        "language": payload.get("language", ""),
                        "related_laws": payload.get("related_laws", []),
                        "applicable_sectors": payload.get("applicable_sectors", []),
                        "legal_forms": payload.get("legal_forms", []),
                        "regions": payload.get("regions", []),
                        "summary": payload.get("summary", ""),
                        "chunk_index": payload.get("chunk_index", 0),
                    },
                ))

            # 5. Compute confidence
            scores = [c.score for c in chunks]
            confidence = self._compute_confidence(scores)
            is_confident = confidence >= confidence_threshold

            # Metrics
            latency = time.monotonic() - start_time
            RETRIEVAL_REQUESTS.labels(status="success").inc()
            RETRIEVAL_LATENCY.observe(latency)
            RETRIEVAL_CONFIDENCE.observe(confidence)

            log.info(
                "retrieval_complete",
                results=len(chunks),
                confidence=round(confidence, 3),
                is_confident=is_confident,
                latency_s=round(latency, 3),
            )

            return RetrievalResult(
                chunks=chunks,
                confidence=confidence,
                query_embedding=query_embedding,
                total_results=len(chunks),
                is_confident=is_confident,
            )

        except RetrievalError:
            raise
        except Exception as exc:
            latency = time.monotonic() - start_time
            RETRIEVAL_REQUESTS.labels(status="error").inc()
            RETRIEVAL_LATENCY.observe(latency)

            log.error("retrieval_failed", error=str(exc))

            raise RetrievalError(
                message=f"Retrieval failed: {exc}",
                details={"tenant": tenant.slug, "query_length": len(query)},
            ) from exc

    def _build_qdrant_filter(
        self,
        filters: dict | None,
        language: str | None,
    ) -> Filter | None:
        """Build Qdrant Filter from user-provided filter dict.

        Supports:
            - language: MatchValue (exact match)
            - applicable_sectors, legal_forms, related_laws, regions: MatchAny
        """
        conditions: list[FieldCondition] = []

        # Language filter (exact match)
        if language:
            conditions.append(
                FieldCondition(key="language", match=MatchValue(value=language))
            )

        # Metadata filters (MatchAny for array fields)
        if filters:
            for field_name, values in filters.items():
                if field_name in _MATCH_ANY_FIELDS and values:
                    if isinstance(values, list):
                        conditions.append(
                            FieldCondition(
                                key=field_name,
                                match=MatchAny(any=values),
                            )
                        )
                    elif isinstance(values, str):
                        conditions.append(
                            FieldCondition(
                                key=field_name,
                                match=MatchValue(value=values),
                            )
                        )

        if not conditions:
            return None

        return Filter(must=conditions)

    @staticmethod
    def _compute_confidence(scores: list[float]) -> float:
        """Compute confidence as average of top-3 similarity scores.

        Returns 0.0 if no scores are available.
        """
        if not scores:
            return 0.0
        top_scores = sorted(scores, reverse=True)[:3]
        return sum(top_scores) / len(top_scores)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_retrieval_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    """Get or create the RetrievalService singleton."""
    global _retrieval_service  # noqa: PLW0603
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
