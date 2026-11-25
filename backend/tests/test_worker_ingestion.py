"""Tests for ARQ ingestion worker tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import IngestionError
from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus
from app.services.rag.extractors import ExtractedDocument, PageSpan

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_doc_orm(
    doc_id: uuid.UUID,
    file_path: str = "kb/abc/guide.pdf",
    title: str = "Guide Investisseur",
    status: KBDocumentStatus = KBDocumentStatus.pending,
) -> MagicMock:
    mock = MagicMock()
    mock.id = doc_id
    mock.file_path = file_path
    mock.title = title
    mock.status = status
    mock.error_message = None
    return mock


def _mock_tenant_session(doc_orm=None):
    """Create a mock for tenant.db_session() context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc_orm
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    return mock_session


def _mock_minio_response(content: bytes = b"Document text content") -> tuple:
    """Create mock MinIO client + response."""
    mock_response = AsyncMock()
    mock_response.read = AsyncMock(return_value=content)
    mock_response.close = MagicMock()
    mock_response.release = AsyncMock()

    mock_minio = MagicMock()
    mock_minio.get_object = AsyncMock(return_value=mock_response)
    return mock_minio


class TestIngestDocumentTask:
    @pytest.mark.asyncio
    async def test_recovery_selects_approved_stale_jobs_with_stable_ids(self):
        from app.workers.ingestion import _recover_tenant_documents

        doc_id = uuid.uuid4()
        updated_at = datetime(2026, 1, 1, tzinfo=UTC)
        session = _mock_tenant_session()
        session.execute.return_value.all.return_value = [(doc_id, updated_at)]
        redis = MagicMock()
        redis.enqueue_job = AsyncMock(return_value=object())
        with patch.object(TenantContext, "db_session", return_value=session):
            assert (
                await _recover_tenant_documents(
                    {"redis": redis}, TEST_TENANT, updated_at + timedelta(hours=1)
                )
                == 1
            )
            assert (
                await _recover_tenant_documents(
                    {"redis": redis}, TEST_TENANT, updated_at + timedelta(hours=1)
                )
                == 1
            )
        first, second = redis.enqueue_job.await_args_list
        assert first.kwargs["_job_id"] == second.kwargs["_job_id"]
        assert first.args == ("ingest_document_task", TEST_TENANT.slug, str(doc_id))
        sql = str(session.execute.await_args.args[0])
        assert "validated_at IS NOT NULL" in sql and "expires_at" in sql

    @pytest.mark.asyncio
    async def test_ingest_success(self):
        """Ingest task runs full pipeline and returns chunk count."""
        from app.workers.ingestion import ingest_document_task

        doc_id = uuid.uuid4()
        doc_orm = _make_doc_orm(doc_id)
        mock_minio = _mock_minio_response()
        mock_session = _mock_tenant_session(doc_orm)

        mock_service = MagicMock()
        mock_service.ingest_document = AsyncMock(return_value=8)

        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(TenantContext, "db_session", return_value=mock_session),
            patch("app.core.minio.get_minio", return_value=mock_minio),
            patch(
                "app.services.rag.ingestion.get_ingestion_service",
                return_value=mock_service,
            ),
            patch(
                "app.workers.ingestion.extract_document",
                return_value=ExtractedDocument("Extracted text content", (PageSpan(2, 0, 22),)),
            ),
        ):
            result = await ingest_document_task({}, "rabat", str(doc_id))

        assert result["status"] == "ok"
        assert result["chunk_count"] == 8
        mock_service.ingest_document.assert_called_once()
        assert mock_service.ingest_document.await_args.kwargs["pages"] == (PageSpan(2, 0, 22),)

    @pytest.mark.asyncio
    async def test_ingest_document_not_found(self):
        """Ingest task returns not_found if document doesn't exist."""
        from app.workers.ingestion import ingest_document_task

        doc_id = uuid.uuid4()
        mock_session = _mock_tenant_session(doc_orm=None)

        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(TenantContext, "db_session", return_value=mock_session),
        ):
            result = await ingest_document_task({}, "rabat", str(doc_id))

        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_ingest_extraction_error_raises(self):
        """Ingest task raises when extraction fails."""
        from app.workers.ingestion import ingest_document_task

        doc_id = uuid.uuid4()
        doc_orm = _make_doc_orm(doc_id)
        mock_minio = _mock_minio_response(b"bad content")

        # Two sessions: one for fetch, one for error status update
        mock_session_fetch = _mock_tenant_session(doc_orm)
        mock_session_error = _mock_tenant_session(doc_orm)
        session_calls = iter([mock_session_fetch, mock_session_error])

        def session_factory():
            return next(session_calls)

        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(
                TenantContext,
                "db_session",
                side_effect=session_factory,
            ),
            patch("app.core.minio.get_minio", return_value=mock_minio),
            patch(
                "app.workers.ingestion.extract_document",
                side_effect=IngestionError("Extraction failed"),
            ),
            pytest.raises(IngestionError),
        ):
            await ingest_document_task({}, "rabat", str(doc_id))


class TestReindexDocumentTask:
    @pytest.mark.asyncio
    async def test_error_handler_preserves_revoked_status(self):
        from app.workers.ingestion import _mark_document_error

        doc_id = uuid.uuid4()
        document = _make_doc_orm(doc_id, status=KBDocumentStatus.rejected)
        session = _mock_tenant_session(document)
        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(TenantContext, "db_session", return_value=session),
        ):
            await _mark_document_error("rabat", doc_id)
        assert document.status == KBDocumentStatus.rejected
        assert "FOR UPDATE" in str(session.execute.await_args.args[0])

    @pytest.mark.asyncio
    async def test_extraction_failure_sets_error_without_reindexing(self):
        from app.workers.ingestion import reindex_document_task

        doc_id = uuid.uuid4()
        document = _make_doc_orm(doc_id)
        session = _mock_tenant_session(document)
        service = MagicMock()
        service.reindex_document = AsyncMock()
        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(TenantContext, "db_session", return_value=session),
            patch(
                "app.core.minio.get_object_bytes", new_callable=AsyncMock, return_value=b"invalid"
            ),
            patch("app.services.rag.ingestion.get_ingestion_service", return_value=service),
            patch(
                "app.workers.ingestion.extract_document",
                side_effect=IngestionError("sensitive detail"),
            ),
            pytest.raises(IngestionError),
        ):
            await reindex_document_task({}, "rabat", str(doc_id))

        assert document.status == KBDocumentStatus.error
        assert "sensitive detail" not in document.error_message
        service.reindex_document.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reindex_success(self):
        """Reindex task runs full pipeline and returns chunk count."""
        from app.workers.ingestion import reindex_document_task

        doc_id = uuid.uuid4()
        doc_orm = _make_doc_orm(doc_id, status=KBDocumentStatus.indexed)
        mock_minio = _mock_minio_response()
        mock_session = _mock_tenant_session(doc_orm)

        mock_service = MagicMock()
        mock_service.reindex_document = AsyncMock(return_value=12)

        with (
            patch(
                "app.core.tenant.TenantResolver.from_slug",
                new_callable=AsyncMock,
                return_value=TEST_TENANT,
            ),
            patch.object(TenantContext, "db_session", return_value=mock_session),
            patch("app.core.minio.get_minio", return_value=mock_minio),
            patch(
                "app.services.rag.ingestion.get_ingestion_service",
                return_value=mock_service,
            ),
            patch(
                "app.workers.ingestion.extract_document",
                return_value=ExtractedDocument("Reindexed text", (PageSpan(3, 0, 14),)),
            ),
        ):
            result = await reindex_document_task({}, "rabat", str(doc_id))

        assert result["status"] == "ok"
        assert result["chunk_count"] == 12
        mock_service.reindex_document.assert_called_once()
        assert mock_service.reindex_document.await_args.kwargs["pages"] == (PageSpan(3, 0, 14),)
