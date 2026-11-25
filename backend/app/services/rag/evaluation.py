"""Measured, tenant-scoped RAG retrieval monitoring without deployment gates."""

from __future__ import annotations

import math
import statistics
import time
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

        recall_at_3 = recall_at_5 = eligible_recall = citation_hits = abstention_hits = 0
        latencies: list[float] = []
        for case in cases:
            safe_query = get_pii_masker().mask(case.query).masked_text
            start = time.monotonic()
            retrieval = await get_retrieval_service().retrieve(
                tenant, safe_query, language=case.language, top_k=5
            )
            latencies.append((time.monotonic() - start) * 1000)
            expected_document_ids = {str(value) for value in (case.expected_document_ids or [])}
            if expected_document_ids and not case.expects_abstention:
                eligible_recall += 1
                recall_at_3 += int(
                    bool(
                        expected_document_ids.intersection(
                            chunk.document_id for chunk in retrieval.chunks[:3]
                        )
                    )
                )
                recall_at_5 += int(
                    bool(
                        expected_document_ids.intersection(
                            chunk.document_id for chunk in retrieval.chunks[:5]
                        )
                    )
                )
            citations = [
                chunk
                for chunk in retrieval.chunks
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
        total = len(cases)
        sorted_latencies = sorted(latencies)
        metrics = {
            "source_recall_at_3": round(recall_at_3 / eligible_recall, 4)
            if eligible_recall
            else None,
            "source_recall_at_5": round(recall_at_5 / eligible_recall, 4)
            if eligible_recall
            else None,
            "recall_evaluated_cases": eligible_recall,
            "citation_coverage": round(citation_hits / total, 4) if total else None,
            "abstention_accuracy": round(abstention_hits / total, 4) if total else None,
            "retrieval_latency_p50_ms": round(statistics.median(latencies), 1)
            if latencies
            else None,
            "retrieval_latency_p95_ms": (
                round(sorted_latencies[math.ceil(len(sorted_latencies) * 0.95) - 1], 1)
                if sorted_latencies
                else None
            ),
            "human_faithfulness_reviewed": sum(
                case.human_faithfulness is not None for case in cases
            ),
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
