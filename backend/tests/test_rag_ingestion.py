"""Tests for IngestionService — all external dependencies mocked."""

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before any app imports
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("REDIS_PASSWORD", "test")

from app.core.exceptions import IngestionError
from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus
from app.schemas.rag import ChunkResult


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

DOCUMENT_ID = uuid.uuid4()

SAMPLE_CHUNKS = [
    ChunkResult(content="Chunk one about investissements.", chunk_index=0, token_count=10, start_char=0, end_char=30),
    ChunkResult(content="Chunk two about fiscalité.", chunk_index=1, token_count=10, start_char=31, end_char=55),
    ChunkResult(content="Chunk three about création d'entreprise.", chunk_index=2, token_count=12, start_char=56, end_char=90),
]

SAMPLE_VECTORS = [
    [0.1] * 768,
    [0.2] * 768,
    [0.3] * 768,
]

SAMPLE_METADATA = [
    {"related_laws": ["Loi 47-18"], "applicable_sectors": ["industrie"], "legal_forms": [], "regions": ["RSK"], "language": "fr", "summary": "Investissements"},
    {"related_laws": [], "applicable_sectors": ["commerce"], "legal_forms": ["SARL"], "regions": [], "language": "fr", "summary": "Fiscalité"},
    {"related_laws": [], "applicable_sectors": [], "legal_forms": ["SA"], "regions": ["RSK"], "language": "fr", "summary": "Création"},
]


def _mock_db_session():
    """Create a mock async DB session with context manager support."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # Default: no duplicate found
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_result.fetchall.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    return mock_session


def _make_ingestion_service(
    mock_chunker=None,
    mock_embedder=None,
    mock_gemini=None,
    mock_qdrant=None,
    mock_session=None,
):
    """Create IngestionService with mocked dependencies.

    All dependencies are stored at __init__ time, so patching only needs
    to be active during construction. The db_session mock is applied via
    a patcher that must be used as a context manager around the test call.
    """
    if mock_chunker is None:
        mock_chunker = MagicMock()
        mock_chunker.chunk_text.return_value = SAMPLE_CHUNKS

    if mock_embedder is None:
        mock_embedder = MagicMock()
        mock_embedder.embed_batch = AsyncMock(return_value=SAMPLE_VECTORS)

    if mock_gemini is None:
        mock_gemini = MagicMock()
        mock_gemini.generate_simple = AsyncMock(
            return_value=json.dumps(SAMPLE_METADATA)
        )

    if mock_qdrant is None:
        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock()
        mock_qdrant.delete = AsyncMock()

    if mock_session is None:
        mock_session = _mock_db_session()

    with (
        patch("app.services.rag.ingestion.get_chunking_service", return_value=mock_chunker),
        patch("app.services.rag.ingestion.get_embedding_service", return_value=mock_embedder),
        patch("app.services.rag.ingestion.get_gemini_service", return_value=mock_gemini),
        patch("app.services.rag.ingestion.get_qdrant", return_value=mock_qdrant),
    ):
        from app.services.rag.ingestion import IngestionService

        service = IngestionService()

    # Patch tenant.db_session to return our mock session
    patcher = patch.object(
        TenantContext, "db_session",
        return_value=mock_session,
    )

    return service, mock_qdrant, mock_embedder, mock_chunker, mock_gemini, mock_session, patcher


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestDocumentSuccess:
    @pytest.mark.asyncio
    async def test_ingest_full_pipeline(self):
        """Full ingestion pipeline: chunks created, Qdrant upserted, status=indexed."""
        service, mock_qdrant, mock_embedder, mock_chunker, _, mock_session, patcher = (
            _make_ingestion_service()
        )

        with patcher:
            result = await service.ingest_document(
                tenant=TEST_TENANT,
                document_id=DOCUMENT_ID,
                content="Some document content about investissements au Maroc.",
                title="Test Document",
            )

        # Should return chunk count
        assert result == 3

        # Chunker was called
        mock_chunker.chunk_text.assert_called_once()

        # Embedder was called with chunk contents
        mock_embedder.embed_batch.assert_awaited_once()
        embed_call_args = mock_embedder.embed_batch.call_args
        assert len(embed_call_args[0][0]) == 3  # 3 texts

        # Qdrant upsert was called
        mock_qdrant.upsert.assert_awaited()
        upsert_call = mock_qdrant.upsert.call_args
        assert upsert_call.kwargs["collection_name"] == "kb_rabat"

        # DB operations: multiple execute calls (status updates + dedup check + chunk inserts)
        assert mock_session.commit.await_count >= 1


class TestIngestDocumentDedup:
    @pytest.mark.asyncio
    async def test_duplicate_content_skips_ingestion(self):
        """Document with same content_hash as existing indexed doc → skip."""
        mock_session = _mock_db_session()

        # First execute: status update (indexing) → no result needed
        # Second execute: dedup check → return an existing doc
        mock_existing = MagicMock()
        mock_existing.first.return_value = (uuid.uuid4(),)  # Found duplicate

        call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Dedup check returns a match
                return mock_existing
            return MagicMock(first=MagicMock(return_value=None), fetchall=MagicMock(return_value=[]))

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)

        mock_qdrant = AsyncMock()
        service, _, _, _, _, _, patcher = _make_ingestion_service(
            mock_qdrant=mock_qdrant,
            mock_session=mock_session,
        )

        with patcher:
            result = await service.ingest_document(
                tenant=TEST_TENANT,
                document_id=DOCUMENT_ID,
                content="Duplicate content here.",
                title="Duplicate Doc",
            )

        # Should return 0 (skipped)
        assert result == 0

        # Qdrant should NOT have been called for upsert
        mock_qdrant.upsert.assert_not_awaited()


class TestIngestDocumentFailure:
    @pytest.mark.asyncio
    async def test_qdrant_error_sets_status_error(self):
        """Qdrant upsert failure → status=error, raises IngestionError."""
        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock(side_effect=Exception("Qdrant connection refused"))

        service, _, _, _, _, mock_session, patcher = _make_ingestion_service(
            mock_qdrant=mock_qdrant,
        )

        with patcher:
            with pytest.raises(IngestionError, match="Ingestion failed"):
                await service.ingest_document(
                    tenant=TEST_TENANT,
                    document_id=DOCUMENT_ID,
                    content="Content that will fail.",
                    title="Failing Doc",
                )

        # Status should have been updated to error (last execute call with update)
        assert mock_session.execute.await_count >= 2  # At least: indexing + error


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_removes_from_qdrant_and_db(self):
        """delete_document removes points from Qdrant and chunks from DB."""
        mock_session = _mock_db_session()

        # First query: get qdrant_point_ids
        mock_result_with_ids = MagicMock()
        mock_result_with_ids.fetchall.return_value = [
            ("point-1",), ("point-2",), ("point-3",),
        ]
        mock_result_with_ids.first.return_value = None

        call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result_with_ids
            return MagicMock(first=MagicMock(return_value=None), fetchall=MagicMock(return_value=[]))

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)

        mock_qdrant = AsyncMock()
        service, _, _, _, _, _, patcher = _make_ingestion_service(
            mock_qdrant=mock_qdrant,
            mock_session=mock_session,
        )

        with patcher:
            await service.delete_document(TEST_TENANT, DOCUMENT_ID)

        # Qdrant delete was called with the point IDs
        mock_qdrant.delete.assert_awaited_once()
        delete_call = mock_qdrant.delete.call_args
        assert delete_call.kwargs["collection_name"] == "kb_rabat"
        assert delete_call.kwargs["points_selector"] == ["point-1", "point-2", "point-3"]


class TestEnrichMetadata:
    @pytest.mark.asyncio
    async def test_valid_json_parsed_correctly(self):
        """Valid Gemini JSON → parsed MetadataEnrichment dicts."""
        mock_gemini = MagicMock()
        mock_gemini.generate_simple = AsyncMock(
            return_value=json.dumps([
                {"related_laws": ["Loi 47-18"], "applicable_sectors": ["industrie"], "language": "fr", "summary": "Test"},
            ])
        )

        service, _, _, _, _, _, patcher = _make_ingestion_service(mock_gemini=mock_gemini)

        with patcher:
            result = await service._enrich_metadata(
                ["Some chunk content about investissements."],
                TEST_TENANT,
            )

        assert len(result) == 1
        assert result[0]["related_laws"] == ["Loi 47-18"]
        assert result[0]["applicable_sectors"] == ["industrie"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_dicts(self):
        """Invalid Gemini response → empty metadata dicts (best-effort)."""
        mock_gemini = MagicMock()
        mock_gemini.generate_simple = AsyncMock(
            return_value="This is not valid JSON at all"
        )

        service, _, _, _, _, _, patcher = _make_ingestion_service(mock_gemini=mock_gemini)

        with patcher:
            result = await service._enrich_metadata(
                ["Chunk 1", "Chunk 2"],
                TEST_TENANT,
            )

        # Should return empty dicts, not raise
        assert len(result) == 2
        assert result[0] == {}
        assert result[1] == {}

    @pytest.mark.asyncio
    async def test_gemini_exception_returns_empty_dicts(self):
        """Gemini API exception → empty metadata dicts (never blocks ingestion)."""
        mock_gemini = MagicMock()
        mock_gemini.generate_simple = AsyncMock(
            side_effect=Exception("Gemini API down")
        )

        service, _, _, _, _, _, patcher = _make_ingestion_service(mock_gemini=mock_gemini)

        with patcher:
            result = await service._enrich_metadata(
                ["Chunk 1"],
                TEST_TENANT,
            )

        assert len(result) == 1
        assert result[0] == {}
