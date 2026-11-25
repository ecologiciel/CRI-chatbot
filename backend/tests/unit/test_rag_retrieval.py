"""Unit tests for RetrievalService — embed query, Qdrant search, confidence scoring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import RetrievalError
from app.services.rag.retrieval import RetrievalService

_EMBED_PATCH = "app.services.rag.retrieval.get_embedding_service"
_QDRANT_PATCH = "app.services.rag.retrieval.get_qdrant"

DIMENSION = 768


def test_published_filter_is_applied_alongside_existing_conditions():
    from qdrant_client.models import FieldCondition, Filter, HasIdCondition, MatchValue

    original = Filter(must=[FieldCondition(key="language", match=MatchValue(value="fr"))])
    result = RetrievalService._restrict_to_published(original, ["00000000-0000-0000-0000-000000000001"])
    assert len(result.must) == 2
    assert isinstance(result.must[-1], HasIdCondition)
    assert result.must[-1].has_id == ["00000000-0000-0000-0000-000000000001"]
    assert len(original.must) == 1


@pytest.mark.asyncio
async def test_published_point_query_uses_tenant_scoped_session(tenant_context):
    from contextlib import asynccontextmanager

    from app.core.tenant import TenantContext

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["published-point"]
    session.execute.return_value = result

    @asynccontextmanager
    async def tenant_session(_self):
        yield session

    service, _, _ = _make_service()
    with patch.object(TenantContext, "db_session", tenant_session):
        assert await RetrievalService._published_point_ids(service, tenant_context) == ["published-point"]
    statement = str(session.execute.await_args.args[0])
    assert "active_index_version" in statement and "index_version" in statement


def _make_qdrant_point(point_id, score, content="chunk text", doc_id="doc-1"):
    """Create a mock Qdrant ScoredPoint."""
    point = MagicMock()
    point.id = point_id
    point.score = score
    point.payload = {
        "document_id": doc_id,
        "content": content,
        "title": "Test Doc",
        "language": "fr",
        "related_laws": [],
        "applicable_sectors": [],
        "legal_forms": [],
        "regions": [],
        "summary": "summary",
        "chunk_index": 0,
    }
    return point


def _make_service(qdrant_results=None, embed_error=False):
    """Create RetrievalService with mocked dependencies."""
    mock_embedder = AsyncMock()
    if embed_error:
        mock_embedder.embed_single = AsyncMock(
            side_effect=RuntimeError("embed failed"),
        )
    else:
        mock_embedder.embed_single = AsyncMock(return_value=[0.1] * DIMENSION)

    mock_qdrant = AsyncMock()
    mock_qdrant.search = AsyncMock(return_value=qdrant_results or [])

    with (
        patch(_EMBED_PATCH, return_value=mock_embedder),
        patch(_QDRANT_PATCH, return_value=mock_qdrant),
    ):
        service = RetrievalService()
        service._published_point_ids = AsyncMock(return_value=["00000000-0000-0000-0000-000000000001"])
        return service, mock_embedder, mock_qdrant


class TestRetrieveSuccess:
    """Successful retrieval returns chunks with scores."""

    @pytest.mark.asyncio
    async def test_returns_chunks_with_scores(self, tenant_context):
        """3 Qdrant results map to 3 RetrievedChunks with confidence."""
        points = [
            _make_qdrant_point("p1", 0.9, "Chunk A"),
            _make_qdrant_point("p2", 0.8, "Chunk B"),
            _make_qdrant_point("p3", 0.7, "Chunk C"),
        ]
        service, _, qdrant = _make_service(qdrant_results=points)

        result = await service.retrieve(tenant_context, "test query")

        assert len(result.chunks) == 3
        assert result.chunks[0].score == 0.9
        assert result.total_results == 3
        # Confidence = avg of top-3: (0.9+0.8+0.7)/3 = 0.8
        assert abs(result.confidence - 0.8) < 0.01
        assert result.is_confident is True

    @pytest.mark.asyncio
    async def test_collection_uses_tenant_slug(self, tenant_context):
        """Qdrant search uses tenant's collection name kb_{slug}."""
        service, _, qdrant = _make_service()

        await service.retrieve(tenant_context, "test")

        call_kwargs = qdrant.search.call_args
        assert call_kwargs.kwargs["collection_name"] == "kb_rabat"


class TestRetrieveWithFilters:
    """Metadata filters build Qdrant Filter conditions."""

    @pytest.mark.asyncio
    async def test_metadata_filters_passed(self, tenant_context):
        """sectors + language build a multi-condition Filter."""
        service, _, qdrant = _make_service()

        await service.retrieve(
            tenant_context,
            "test",
            filters={"applicable_sectors": ["industrie", "tourisme"]},
            language="fr",
        )

        call_kwargs = qdrant.search.call_args
        qdrant_filter = call_kwargs.kwargs.get("query_filter")
        assert qdrant_filter is not None
        assert len(qdrant_filter.must) == 3  # language + sectors + published IDs


class TestRetrieveEmpty:
    """Empty results return zero confidence."""

    @pytest.mark.asyncio
    async def test_no_results_zero_confidence(self, tenant_context):
        """Empty Qdrant search returns confidence=0.0, is_confident=False."""
        service, _, _ = _make_service(qdrant_results=[])

        result = await service.retrieve(tenant_context, "unknown topic")

        assert result.chunks == []
        assert result.confidence == 0.0
        assert result.is_confident is False


class TestRetrieveErrors:
    """Errors are wrapped in RetrievalError."""

    @pytest.mark.asyncio
    async def test_embedding_failure_raises(self, tenant_context):
        """EmbeddingError during embed is wrapped in RetrievalError."""
        service, _, _ = _make_service(embed_error=True)

        with pytest.raises(RetrievalError, match="Retrieval failed"):
            await service.retrieve(tenant_context, "test")
