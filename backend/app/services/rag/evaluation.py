"""Measured, tenant-scoped RAG retrieval monitoring without deployment gates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.tenant import TenantContext
from app.models.rag_evaluation import RAGEvaluationCase, RAGEvaluationRun
from app.services.guardrails.pii_masker import get_pii_masker
from app.services.rag.retrieval import get_retrieval_service


class RAGEvaluationService:
    async def run(self, tenant: TenantContext, triggered_by: uuid.UUID) -> RAGEvaluationRun:
        async with tenant.db_session() as session:
            result = await session.execute(
                select(RAGEvaluationCase).where(RAGEvaluationCase.is_active.is_(True))
            )
            cases = list(result.scalars())

        recall_hits = citation_hits = abstention_hits = 0
        latencies: list[float] = []
        for case in cases:
            safe_query = get_pii_masker().mask(case.query).masked_text
            retrieval = await get_retrieval_service().retrieve(
                tenant, safe_query, language=case.language, top_k=3
            )
            actual_document_ids = {chunk.document_id for chunk in retrieval.chunks}
            expected_document_ids = {str(value) for value in (case.expected_document_ids or [])}
            if expected_document_ids and expected_document_ids.intersection(actual_document_ids):
                recall_hits += 1
            citations = [
                chunk for chunk in retrieval.chunks
                if chunk.metadata.get("title")
                and chunk.metadata.get("source_reference")
                and chunk.metadata.get("source_version")
                and chunk.metadata.get("published_at")
            ]
            if citations:
                citation_hits += 1
            predicted_abstention = not retrieval.is_confident
            if predicted_abstention == case.expects_abstention:
                abstention_hits += 1
            latencies.append(0.0)  # Retrieval metrics remain in Prometheus; run stores aggregate outcomes.

        total = len(cases)
        metrics = {
            "source_recall_at_3": round(recall_hits / total, 4) if total else 0.0,
            "citation_coverage": round(citation_hits / total, 4) if total else 0.0,
            "abstention_accuracy": round(abstention_hits / total, 4) if total else 0.0,
            "human_faithfulness_reviewed": sum(case.human_faithfulness is not None for case in cases),
            "mode": "monitoring_non_blocking",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        async with tenant.db_session() as session:
            run = RAGEvaluationRun(case_count=total, metrics=metrics, triggered_by=triggered_by)
            session.add(run)
            await session.flush()
            await session.refresh(run)
            return run


_service: RAGEvaluationService | None = None


def get_rag_evaluation_service() -> RAGEvaluationService:
    global _service
    if _service is None:
        _service = RAGEvaluationService()
    return _service
