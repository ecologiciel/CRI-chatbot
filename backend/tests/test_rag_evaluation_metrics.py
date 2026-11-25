"""Evaluation metrics must distinguish answerable and abstention cases."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.evaluation import RAGEvaluationService


@pytest.mark.asyncio
async def test_recall_denominator_excludes_abstentions_and_missing_labels():
    target = str(uuid.uuid4())
    cases = [
        SimpleNamespace(
            id=uuid.uuid4(),
            query="question 1",
            language="fr",
            expected_document_ids=[target],
            expects_abstention=False,
            human_faithfulness=True,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            query="question 2",
            language="fr",
            expected_document_ids=[target],
            expects_abstention=False,
            human_faithfulness=None,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            query="sans réponse",
            language="fr",
            expected_document_ids=[],
            expects_abstention=True,
            human_faithfulness=None,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            query="sans étiquette",
            language="fr",
            expected_document_ids=[],
            expects_abstention=False,
            human_faithfulness=None,
        ),
    ]

    def chunk(doc_id, metadata=None):
        return SimpleNamespace(document_id=doc_id, metadata=metadata or {})

    provenance = {
        "title": "Guide",
        "source_reference": "ref",
        "source_version": "1",
        "published_at": "2026-01-01",
    }
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        side_effect=[
            SimpleNamespace(
                chunks=[chunk("a"), chunk("b"), chunk("c"), chunk(target, provenance)],
                is_confident=True,
            ),
            SimpleNamespace(chunks=[chunk("other")], is_confident=False),
            SimpleNamespace(chunks=[], is_confident=False),
            SimpleNamespace(chunks=[], is_confident=False),
        ]
    )
    result = MagicMock()
    result.scalars.return_value = cases
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    session.add = MagicMock()
    tenant = MagicMock()
    tenant.db_session.return_value = session
    with patch("app.services.rag.evaluation.get_retrieval_service", return_value=retriever):
        run = await RAGEvaluationService().run(tenant, uuid.uuid4())
    assert run.case_count == 4
    assert run.metrics["recall_evaluated_cases"] == 2
    assert run.metrics["source_recall_at_3"] == 0
    assert run.metrics["source_recall_at_5"] == 0.5
    assert run.metrics["abstention_accuracy"] == 0.5
    assert run.metrics["confidence_abstention_proxy"] == 0.5
    assert run.metrics["citation_coverage"] == 0.25
    assert run.metrics["human_faithfulness_reviewed"] == 1
    results = run.metrics["case_results"]
    assert results[0]["expected_document_rank"] == 4
    assert results[0]["case_id"] == str(cases[0].id)
    assert results[0]["retrieved_document_ids"] == ["a", "b", "c", target]
    assert results[1]["recall_evaluated"] is True
    assert results[1]["expected_document_rank"] is None
    assert results[2]["recall_evaluated"] is False
    assert results[2]["expects_abstention"] is True
    assert results[3]["recall_evaluated"] is False
    assert run.metrics["retrieval_latency_p95_ms"] >= run.metrics["retrieval_latency_p50_ms"] >= 0
    assert all(call.kwargs["top_k"] == 5 for call in retriever.retrieve.await_args_list)
