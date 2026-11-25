"""Unit tests for IngestionService — chunk, enrich, embed, Qdrant upsert, DB save."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import IngestionError
from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus
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
    def result_for_statement(statement, *args, **kwargs):
        sql = str(statement)
        if "max(kb_chunks.index_version)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = None
            return result
        if sql.startswith("SELECT kb_documents.") and "kb_documents.content_hash =" not in sql:
            result = MagicMock()
            result.scalar_one.return_value = MagicMock(active_index_version=None)
            return result
        return mock_result
    session.execute = AsyncMock(side_effect=result_for_statement)
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
            service._publish_candidate = AsyncMock()
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
    async def test_duplicate_content_is_not_marked_indexed(self, tenant_context):
        """A duplicate cannot be reported as indexed without its own vectors."""
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
            with pytest.raises(IngestionError, match="identique"):
                await service.ingest_document(
                    tenant_context,
                    DOC_ID,
                    "Duplicate text.",
                    "Doc",
                )

        mock_qdrant.upsert.assert_not_called()


class TestQdrantFailure:
    @pytest.mark.asyncio
    async def test_revoked_candidate_cannot_be_published(self, tenant_context):
        from app.core.exceptions import ValidationError

        document = MagicMock(active_index_version=1, status=KBDocumentStatus.rejected)
        result = MagicMock()
        result.scalar_one_or_none.return_value = document
        session = _make_session()
        session.execute = AsyncMock(return_value=result)
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH), patch(_QDRANT_PATCH),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            service._verify_candidate_vectors = AsyncMock()
            with pytest.raises(ValidationError):
                await service._publish_candidate(tenant_context, DOC_ID, 1, 2, 1, "hash")
            service._verify_candidate_vectors.assert_not_awaited()
        assert document.active_index_version == 1

    @pytest.mark.asyncio
    async def test_candidate_publication_requires_complete_verified_vectors(self, tenant_context):
        document = MagicMock(active_index_version=1, chunk_count=1, expires_at=None, status=KBDocumentStatus.indexing)
        first, second = MagicMock(), MagicMock()
        first.scalar_one_or_none.return_value = document
        second.all.return_value = [(0, "candidate")]
        session = _make_session()
        session.execute.side_effect = [first, second, first, second]
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH), patch(_QDRANT_PATCH),
            _make_db_session_patch(session),
        ):
            service = IngestionService()
            service._verify_candidate_vectors = AsyncMock(side_effect=ValueError("incomplete"))
            with pytest.raises(ValueError, match="incomplete"):
                await service._publish_candidate(tenant_context, DOC_ID, 1, 2, 1, "hash")
            assert document.active_index_version == 1
            service._verify_candidate_vectors = AsyncMock()
            await service._publish_candidate(tenant_context, DOC_ID, 1, 2, 1, "hash")
        assert document.active_index_version == 2
        assert document.status.value == "indexed"

    @pytest.mark.asyncio
    async def test_candidate_verification_rejects_missing_and_wrong_generation(self, tenant_context):
        qdrant = AsyncMock()
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH),
            patch(_QDRANT_PATCH, return_value=qdrant),
        ):
            service = IngestionService()
            qdrant.retrieve.return_value = []
            with pytest.raises(ValueError, match="incomplete"):
                await service._verify_candidate_vectors(tenant_context, DOC_ID, 2, ["point"])
            record = MagicMock(id="point", payload={"document_id": str(DOC_ID), "index_version": 3})
            record.vector = [0.1] * DIMENSION
            qdrant.retrieve.return_value = [record]
            with pytest.raises(ValueError, match="does not match"):
                await service._verify_candidate_vectors(tenant_context, DOC_ID, 2, ["point"])
            record.payload["index_version"] = 2
            await service._verify_candidate_vectors(tenant_context, DOC_ID, 2, ["point"])

    @pytest.mark.asyncio
    async def test_candidate_point_ids_are_stable_and_version_specific(self, tenant_context):
        qdrant = AsyncMock()
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH),
            patch(_QDRANT_PATCH, return_value=qdrant),
        ):
            service = IngestionService()
            args = (tenant_context, _make_chunks(1), [[0.1] * DIMENSION], [{}], DOC_ID, "Document", {})
            first = await service._index_qdrant(*args, index_version=2)
            second = await service._index_qdrant(*args, index_version=2)
            third = await service._index_qdrant(*args, index_version=3)
        assert first == second
        assert first != third
        assert qdrant.upsert.await_args.kwargs["points"][0].payload["index_version"] == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("vector", [[0.1] * 767, [float("nan")] * 768])
    async def test_invalid_vector_rejected_before_upsert(self, tenant_context, vector):
        qdrant = AsyncMock()
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH),
            patch(_QDRANT_PATCH, return_value=qdrant),
        ):
            service = IngestionService()
            with pytest.raises(ValueError, match="Invalid embedding"):
                await service._index_qdrant(
                    tenant_context, _make_chunks(1), [vector], [{}], DOC_ID, "Document", {},
                )
        qdrant.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_embedding_rejected_before_upsert(self, tenant_context):
        qdrant = AsyncMock()
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH),
            patch(_QDRANT_PATCH, return_value=qdrant),
        ):
            service = IngestionService()
            with pytest.raises(ValueError, match="Embedding count mismatch"):
                await service._index_qdrant(
                    tenant_context, _make_chunks(2), [[0.1] * DIMENSION], [],
                    DOC_ID, "Document", {},
                )
        qdrant.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_full_chunk_content_is_stored(self, tenant_context):
        qdrant = AsyncMock()
        chunk = ChunkResult(content="a" * 3000, chunk_index=0, token_count=750, start_char=0, end_char=3000)
        with (
            patch(_CHUNKER_PATCH), patch(_EMBED_PATCH), patch(_GEMINI_PATCH),
            patch(_QDRANT_PATCH, return_value=qdrant),
        ):
            service = IngestionService()
            await service._index_qdrant(
                tenant_context, [chunk], [[0.1] * DIMENSION], [{}], DOC_ID, "Document", {},
            )
        assert qdrant.upsert.await_args.kwargs["points"][0].payload["content"] == chunk.content
        assert qdrant.upsert.await_args.kwargs["points"][0].payload["start_char"] == 0
        assert qdrant.upsert.await_args.kwargs["points"][0].payload["end_char"] == 3000

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
            service._publish_candidate = AsyncMock()
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
