"""Unit tests for IngestionService — chunk, enrich, embed, Qdrant upsert, DB save."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import IngestionError
from app.core.tenant import TenantContext
from app.schemas.rag import ChunkResult
from app.services.rag.ingestion import IngestionService

_CHUNKER_PATCH = "app.services.rag.ingestion.get_chunking_service"
_EMBED_PATCH = "app.services.rag.ingestion.get_embedding_service"
_GEMINI_PATCH = "app.services.rag.ingestion.get_gemini_service"
_QDRANT_PATCH = "app.services.rag.ingestion.get_qdrant"

DOC_ID = uuid.uuid4()
DIMENSION = 768


def _make_chunks(count=3):
    return [
        ChunkResult(
            content=f"Chunk content {i}",
            chunk_index=i,
            token_count=100,
            start_char=i * 100,
            end_char=(i + 1) * 100,
        )
        for i in range(count)
    ]


def _make_db_session_patch(mock_session):
    """Patch TenantContext.db_session with a fake that accepts self."""

    @asynccontextmanager
    async def _fake_db(self_arg):
        yield mock_session

    return patch.object(TenantContext, "db_session", _fake_db)


def _make_session(is_duplicate=False, point_ids=None):
    """Create a mock async DB session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.add = MagicMock()

    mock_result = MagicMock()
    mock_result.first.return_value = MagicMock() if is_duplicate else None
    mock_result.fetchall.return_value = [(pid,) for pid in point_ids] if point_ids else []
    session.execute = AsyncMock(return_value=mock_result)
    return session


class TestIngestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_chunk_count(self, tenant_context):
        """Happy path: returns chunk count, Qdrant upserted."""
        chunks = _make_chunks()
        mock_chunker = MagicMock()
        mock_chunker.chunk_text.return_value = chunks

        mock_embedder = AsyncMock()
        mock_embedder.embed_batch = AsyncMock(return_value=[[0.1] * DIMENSION] * 3)

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="[]")

        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock()

        session = _make_session()

        with (
            patch(_CHUNKER_PATCH, return_value=mock_chunker),
            patch(_EMBED_PATCH, return_value=mock_embedder),
            patch(_GEMINI_PATCH, return_value=mock_gemini),
            patch(_QDRANT_PATCH, return_value=mock_qdrant),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            count = await service.ingest_document(
                tenant_context,
                DOC_ID,
                "Full document text.",
                "Test Doc",
            )

        assert count == 3
        mock_qdrant.upsert.assert_called_once()


class TestDuplicateDetection:
    @pytest.mark.asyncio
    async def test_duplicate_content_returns_zero(self, tenant_context):
        """Duplicate SHA256 hash returns 0 chunks."""
        mock_chunker = MagicMock()
        mock_embedder = AsyncMock()
        mock_gemini = AsyncMock()
        mock_qdrant = AsyncMock()

        session = _make_session(is_duplicate=True)

        with (
            patch(_CHUNKER_PATCH, return_value=mock_chunker),
            patch(_EMBED_PATCH, return_value=mock_embedder),
            patch(_GEMINI_PATCH, return_value=mock_gemini),
            patch(_QDRANT_PATCH, return_value=mock_qdrant),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            count = await service.ingest_document(
                tenant_context,
                DOC_ID,
                "Duplicate text.",
                "Doc",
            )

        assert count == 0
        mock_qdrant.upsert.assert_not_called()


class TestQdrantFailure:
    @pytest.mark.asyncio
    async def test_qdrant_failure_raises(self, tenant_context):
        """Qdrant exception wrapped in IngestionError."""
        mock_chunker = MagicMock()
        mock_chunker.chunk_text.return_value = _make_chunks()

        mock_embedder = AsyncMock()
        mock_embedder.embed_batch = AsyncMock(return_value=[[0.1] * DIMENSION] * 3)

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="[]")

        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock(side_effect=RuntimeError("Qdrant down"))

        session = _make_session()

        with (
            patch(_CHUNKER_PATCH, return_value=mock_chunker),
            patch(_EMBED_PATCH, return_value=mock_embedder),
            patch(_GEMINI_PATCH, return_value=mock_gemini),
            patch(_QDRANT_PATCH, return_value=mock_qdrant),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            with pytest.raises(IngestionError, match="Ingestion failed"):
                await service.ingest_document(
                    tenant_context,
                    DOC_ID,
                    "Content.",
                    "Doc",
                )


class TestMetadataEnrichment:
    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_dicts(self, tenant_context):
        """Non-JSON from Gemini doesn't block ingestion."""
        mock_chunker = MagicMock()
        mock_chunker.chunk_text.return_value = _make_chunks()

        mock_embedder = AsyncMock()
        mock_embedder.embed_batch = AsyncMock(return_value=[[0.1] * DIMENSION] * 3)

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="not valid json")

        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock()

        session = _make_session()

        with (
            patch(_CHUNKER_PATCH, return_value=mock_chunker),
            patch(_EMBED_PATCH, return_value=mock_embedder),
            patch(_GEMINI_PATCH, return_value=mock_gemini),
            patch(_QDRANT_PATCH, return_value=mock_qdrant),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            count = await service.ingest_document(
                tenant_context,
                DOC_ID,
                "Content here.",
                "Doc",
            )

        assert count == 3


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_removes_points_and_db(self, tenant_context):
        """delete_document calls Qdrant.delete with point IDs."""
        mock_chunker = MagicMock()
        mock_embedder = AsyncMock()
        mock_gemini = AsyncMock()

        mock_qdrant = AsyncMock()
        mock_qdrant.delete = AsyncMock()

        session = _make_session(point_ids=["point-1", "point-2"])

        with (
            patch(_CHUNKER_PATCH, return_value=mock_chunker),
            patch(_EMBED_PATCH, return_value=mock_embedder),
            patch(_GEMINI_PATCH, return_value=mock_gemini),
            patch(_QDRANT_PATCH, return_value=mock_qdrant),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            await service.delete_document(tenant_context, DOC_ID)

        mock_qdrant.delete.assert_called_once()
