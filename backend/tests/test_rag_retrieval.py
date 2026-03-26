"""Tests for RetrievalService — embedder and Qdrant mocked."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before any app imports
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("REDIS_PASSWORD", "test")

from app.core.exceptions import RetrievalError
from app.core.tenant import TenantContext
from app.schemas.rag import RetrievalResult, RetrievedChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)

QUERY_VECTOR = [0.5] * 768


def _make_scored_point(point_id: str, score: float, payload: dict) -> MagicMock:
    """Create a mock Qdrant ScoredPoint."""
    point = MagicMock()
    point.id = point_id
    point.score = score
    point.payload = payload
    return point


def _make_retrieval_service(
    mock_embedder=None,
    mock_qdrant=None,
):
    """Create RetrievalService with mocked dependencies."""
    if mock_embedder is None:
        mock_embedder = MagicMock()
        mock_embedder.embed_single = AsyncMock(return_value=QUERY_VECTOR)

    if mock_qdrant is None:
        mock_qdrant = AsyncMock()

    with (
        patch("app.services.rag.retrieval.get_embedding_service", return_value=mock_embedder),
        patch("app.services.rag.retrieval.get_qdrant", return_value=mock_qdrant),
    ):
        from app.services.rag.retrieval import RetrievalService

        service = RetrievalService()

    return service, mock_qdrant, mock_embedder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRetrieveSuccess:
    @pytest.mark.asyncio
    async def test_retrieve_returns_chunks_with_scores(self):
        """Successful retrieval returns RetrievalResult with chunks and confidence."""
        doc_id = str(uuid.uuid4())
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[
            _make_scored_point("p1", 0.95, {
                "document_id": doc_id, "content": "Incitations fiscales pour l'industrie.",
                "title": "Guide Investissement", "language": "fr",
                "related_laws": ["Loi 47-18"], "applicable_sectors": ["industrie"],
                "legal_forms": [], "regions": ["RSK"], "summary": "Incitations",
                "chunk_index": 0,
            }),
            _make_scored_point("p2", 0.88, {
                "document_id": doc_id, "content": "Exonération TVA zones d'accélération.",
                "title": "Guide Investissement", "language": "fr",
                "related_laws": [], "applicable_sectors": ["industrie"],
                "legal_forms": ["SARL"], "regions": [], "summary": "TVA",
                "chunk_index": 1,
            }),
            _make_scored_point("p3", 0.82, {
                "document_id": doc_id, "content": "Procédure de création d'entreprise.",
                "title": "Guide Création", "language": "fr",
                "related_laws": [], "applicable_sectors": [],
                "legal_forms": ["SA"], "regions": ["RSK"], "summary": "Création",
                "chunk_index": 0,
            }),
        ])

        service, _, mock_embedder = _make_retrieval_service(mock_qdrant=mock_qdrant)

        result = await service.retrieve(
            tenant=TEST_TENANT,
            query="Quelles sont les incitations fiscales?",
            top_k=5,
        )

        # Verify result type and structure
        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) == 3
        assert result.total_results == 3

        # Verify chunks are RetrievedChunk instances
        for chunk in result.chunks:
            assert isinstance(chunk, RetrievedChunk)
            assert chunk.score > 0

        # Verify confidence (avg of top-3: (0.95 + 0.88 + 0.82) / 3 ≈ 0.883)
        assert 0.88 <= result.confidence <= 0.89
        assert result.is_confident is True

        # Verify query embedding is returned
        assert result.query_embedding == QUERY_VECTOR

        # Verify embedder was called correctly
        mock_embedder.embed_single.assert_awaited_once_with(
            "Quelles sont les incitations fiscales?",
            TEST_TENANT,
            task_type="RETRIEVAL_QUERY",
        )

        # Verify Qdrant was called with correct collection
        mock_qdrant.search.assert_awaited_once()
        search_kwargs = mock_qdrant.search.call_args.kwargs
        assert search_kwargs["collection_name"] == "kb_rabat"
        assert search_kwargs["limit"] == 5


class TestRetrieveWithFilters:
    @pytest.mark.asyncio
    async def test_filters_build_qdrant_filter(self):
        """Metadata filters are correctly translated to Qdrant Filter."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)

        await service.retrieve(
            tenant=TEST_TENANT,
            query="Test query",
            filters={
                "applicable_sectors": ["tourisme", "industrie"],
                "legal_forms": ["SARL"],
            },
            language="fr",
        )

        # Verify Qdrant was called with a filter
        search_kwargs = mock_qdrant.search.call_args.kwargs
        qdrant_filter = search_kwargs["query_filter"]

        assert qdrant_filter is not None
        assert len(qdrant_filter.must) == 3  # language + sectors + legal_forms

        # Check that the filter has the right field conditions
        field_keys = {cond.key for cond in qdrant_filter.must}
        assert "language" in field_keys
        assert "applicable_sectors" in field_keys
        assert "legal_forms" in field_keys

    @pytest.mark.asyncio
    async def test_no_filters_passes_none(self):
        """No filters → query_filter=None."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)

        await service.retrieve(
            tenant=TEST_TENANT,
            query="Test query",
        )

        search_kwargs = mock_qdrant.search.call_args.kwargs
        assert search_kwargs["query_filter"] is None


class TestConfidenceScoring:
    @pytest.mark.asyncio
    async def test_high_scores_confident(self):
        """High similarity scores → is_confident=True."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[
            _make_scored_point("p1", 0.95, {"document_id": "d1", "content": "A"}),
            _make_scored_point("p2", 0.92, {"document_id": "d1", "content": "B"}),
            _make_scored_point("p3", 0.90, {"document_id": "d1", "content": "C"}),
        ])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)
        result = await service.retrieve(TEST_TENANT, "High confidence query")

        # Avg: (0.95 + 0.92 + 0.90) / 3 ≈ 0.923
        assert result.confidence > 0.9
        assert result.is_confident is True

    @pytest.mark.asyncio
    async def test_low_scores_not_confident(self):
        """Low similarity scores → is_confident=False."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[
            _make_scored_point("p1", 0.40, {"document_id": "d1", "content": "X"}),
            _make_scored_point("p2", 0.30, {"document_id": "d1", "content": "Y"}),
            _make_scored_point("p3", 0.20, {"document_id": "d1", "content": "Z"}),
        ])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)
        result = await service.retrieve(TEST_TENANT, "Low confidence query")

        # Avg: (0.40 + 0.30 + 0.20) / 3 = 0.30
        assert result.confidence < 0.7
        assert result.is_confident is False

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        """Custom confidence threshold works correctly."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[
            _make_scored_point("p1", 0.65, {"document_id": "d1", "content": "A"}),
        ])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)

        # With default threshold (0.7) → not confident
        result = await service.retrieve(TEST_TENANT, "Query", confidence_threshold=0.7)
        assert result.is_confident is False

        # With lower threshold (0.5) → confident
        mock_qdrant.search = AsyncMock(return_value=[
            _make_scored_point("p1", 0.65, {"document_id": "d1", "content": "A"}),
        ])
        result = await service.retrieve(TEST_TENANT, "Query", confidence_threshold=0.5)
        assert result.is_confident is True


class TestRetrieveEmpty:
    @pytest.mark.asyncio
    async def test_no_results_returns_empty(self):
        """No Qdrant results → empty chunks, confidence=0.0, is_confident=False."""
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(return_value=[])

        service, _, _ = _make_retrieval_service(mock_qdrant=mock_qdrant)

        result = await service.retrieve(
            tenant=TEST_TENANT,
            query="Question with no matching documents",
        )

        assert isinstance(result, RetrievalResult)
        assert result.chunks == []
        assert result.total_results == 0
        assert result.confidence == 0.0
        assert result.is_confident is False
        assert result.query_embedding == QUERY_VECTOR


class TestRetrieveError:
    @pytest.mark.asyncio
    async def test_embedding_error_raises_retrieval_error(self):
        """Embedding failure → RetrievalError."""
        mock_embedder = MagicMock()
        mock_embedder.embed_single = AsyncMock(
            side_effect=Exception("Embedding API down")
        )

        service, _, _ = _make_retrieval_service(mock_embedder=mock_embedder)

        with pytest.raises(RetrievalError, match="Retrieval failed"):
            await service.retrieve(TEST_TENANT, "Failing query")
