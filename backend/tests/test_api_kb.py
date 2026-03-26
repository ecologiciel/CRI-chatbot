"""Tests for Knowledge Base API endpoints (/api/v1/kb/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched TenantResolver for middleware bypass.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole, KBDocumentStatus
from app.schemas.auth import AdminTokenPayload


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_admin_payload(
    role: str = AdminRole.admin_tenant.value, **overrides
) -> AdminTokenPayload:
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": role,
        "tenant_id": str(TEST_TENANT.id),
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_document_orm(
    doc_id: uuid.UUID | None = None,
    status: KBDocumentStatus = KBDocumentStatus.indexed,
    file_path: str | None = "kb/abc/guide.pdf",
    **overrides,
) -> MagicMock:
    """Create a mock KBDocument ORM object."""
    defaults = {
        "id": doc_id or uuid.uuid4(),
        "title": "Guide de l'investisseur",
        "source_url": None,
        "category": "guide",
        "language": "fr",
        "content_hash": "abc123",
        "file_path": file_path,
        "file_size": 1024,
        "chunk_count": 5,
        "status": status,
        "error_message": None,
        "metadata_": {},
        "created_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "chunks": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_tenant_db_session(
    *,
    scalar_one_or_none=None,
    scalar_one=None,
    scalars_all=None,
):
    """Create a mock for tenant.db_session() async context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none
    mock_result.scalar_one.return_value = scalar_one or scalar_one_or_none

    if scalars_all is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_all
        mock_result.scalars.return_value = mock_scalars

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    return mock_session


def _setup_overrides(role: str = AdminRole.admin_tenant.value) -> AdminTokenPayload:
    """Set RBAC dependency override and return admin payload."""
    payload = _make_admin_payload(role=role)
    app.dependency_overrides[get_current_admin] = lambda: payload
    return payload


def _clear_overrides():
    app.dependency_overrides.pop(get_current_admin, None)


# Common headers for all requests
def _headers() -> dict:
    return {
        "Authorization": "Bearer mock-token",
        "X-Tenant-ID": str(TEST_TENANT.id),
    }


# ---------------------------------------------------------------------------
# Upload document tests
# ---------------------------------------------------------------------------


class TestUploadDocument:
    @pytest.mark.asyncio
    async def test_upload_success(self):
        """POST /kb/documents with valid PDF returns 202."""
        _setup_overrides()
        doc_orm = _make_document_orm(status=KBDocumentStatus.pending)

        mock_session = _mock_tenant_db_session()
        mock_minio = MagicMock()
        mock_minio.put_object = AsyncMock()
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock()

        async def fake_refresh(obj):
            obj.id = doc_orm.id
            obj.title = obj.title if hasattr(obj, "title") and isinstance(obj.title, str) else "Test"
            obj.status = KBDocumentStatus.pending
            obj.source_url = None
            obj.category = getattr(obj, "category", None)
            obj.language = getattr(obj, "language", "fr")
            obj.content_hash = None
            obj.file_path = getattr(obj, "file_path", None)
            obj.file_size = getattr(obj, "file_size", 0)
            obj.chunk_count = 0
            obj.error_message = None
            obj.created_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
            obj.updated_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
                patch("app.api.v1.kb.get_minio", return_value=mock_minio),
                patch("app.api.v1.kb.get_arq_pool", return_value=mock_arq),
                patch("app.api.v1.kb.get_settings") as mock_settings,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_settings.return_value.kb_max_file_size_bytes = 10 * 1024 * 1024
                mock_settings.return_value.kb_max_file_size_mb = 10

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        files={"file": ("guide.pdf", b"%PDF-1.4 test content", "application/pdf")},
                        data={"title": "Guide Investisseur", "language": "fr"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        mock_minio.put_object.assert_called_once()
        mock_arq.enqueue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self):
        """POST /kb/documents with oversized file returns 422."""
        _setup_overrides()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch("app.api.v1.kb.get_settings") as mock_settings,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_settings.return_value.kb_max_file_size_bytes = 100
                mock_settings.return_value.kb_max_file_size_mb = 0

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        files={"file": ("big.pdf", b"x" * 200, "application/pdf")},
                        data={"title": "Big File"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422
        assert "too large" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_upload_bad_extension(self):
        """POST /kb/documents with .exe returns 422."""
        _setup_overrides()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch("app.api.v1.kb.get_settings") as mock_settings,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_settings.return_value.kb_max_file_size_bytes = 10 * 1024 * 1024

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        files={"file": ("virus.exe", b"MZ bad", "application/x-executable")},
                        data={"title": "Bad File"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422
        assert "unsupported" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_upload_viewer_forbidden(self):
        """POST /kb/documents as viewer returns 403."""
        _setup_overrides(role=AdminRole.viewer.value)

        try:
            with patch(
                "app.core.middleware.TenantResolver"
            ) as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        files={"file": ("doc.pdf", b"content", "application/pdf")},
                        data={"title": "Test"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# List documents tests
# ---------------------------------------------------------------------------


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_list_paginated(self):
        """GET /kb/documents returns paginated list."""
        _setup_overrides()
        doc1 = _make_document_orm()
        doc2 = _make_document_orm()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc1, doc2]
        data_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        mock_session.commit = AsyncMock()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/kb/documents?page=1&page_size=10",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        """GET /kb/documents?status=indexed filters results."""
        _setup_overrides()
        doc = _make_document_orm(status=KBDocumentStatus.indexed)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc]
        data_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        mock_session.commit = AsyncMock()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/kb/documents?status=indexed",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json()["total"] == 1


# ---------------------------------------------------------------------------
# Get document detail tests
# ---------------------------------------------------------------------------


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_get_document_detail(self):
        """GET /kb/documents/{id} returns document with chunks."""
        _setup_overrides()
        doc_id = uuid.uuid4()
        chunk_mock = MagicMock(
            id=uuid.uuid4(),
            document_id=doc_id,
            content="Chunk content",
            chunk_index=0,
            qdrant_point_id="point-1",
            token_count=50,
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        doc = _make_document_orm(doc_id=doc_id, chunks=[chunk_mock])

        mock_session = _mock_tenant_db_session(scalar_one_or_none=doc)

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/kb/documents/{doc_id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Guide de l'investisseur"
        assert len(data["chunks"]) == 1

    @pytest.mark.asyncio
    async def test_get_document_not_found(self):
        """GET /kb/documents/{id} for missing document returns 404."""
        _setup_overrides()
        doc_id = uuid.uuid4()

        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/kb/documents/{doc_id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete document tests
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        """DELETE /kb/documents/{id} returns 204."""
        _setup_overrides()
        doc_id = uuid.uuid4()
        doc = _make_document_orm(doc_id=doc_id, file_path="kb/abc/guide.pdf")

        mock_session = _mock_tenant_db_session(scalar_one_or_none=doc)
        mock_minio = MagicMock()
        mock_minio.remove_object = AsyncMock()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
                patch("app.api.v1.kb.get_minio", return_value=mock_minio),
                patch("app.services.rag.ingestion.get_ingestion_service") as mock_ing,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_ing.return_value.delete_document = AsyncMock()

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.delete(
                        f"/api/v1/kb/documents/{doc_id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 204
        mock_ing.return_value.delete_document.assert_called_once()
        mock_minio.remove_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE /kb/documents/{id} for missing document returns 404."""
        _setup_overrides()
        doc_id = uuid.uuid4()

        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.delete(
                        f"/api/v1/kb/documents/{doc_id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Reindex document tests
# ---------------------------------------------------------------------------


class TestReindexDocument:
    @pytest.mark.asyncio
    async def test_reindex_success(self):
        """POST /kb/documents/{id}/reindex returns 202."""
        _setup_overrides()
        doc_id = uuid.uuid4()
        doc = _make_document_orm(
            doc_id=doc_id,
            status=KBDocumentStatus.indexed,
            file_path="kb/abc/guide.pdf",
        )

        mock_session = _mock_tenant_db_session(scalar_one_or_none=doc)
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock()

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
                patch("app.api.v1.kb.get_arq_pool", return_value=mock_arq),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        f"/api/v1/kb/documents/{doc_id}/reindex",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 202
        mock_arq.enqueue_job.assert_called_once_with(
            "reindex_document_task", TEST_TENANT.slug, str(doc_id),
        )

    @pytest.mark.asyncio
    async def test_reindex_no_file_returns_422(self):
        """POST /kb/documents/{id}/reindex without file_path returns 422."""
        _setup_overrides()
        doc_id = uuid.uuid4()
        doc = _make_document_orm(doc_id=doc_id, file_path=None)

        mock_session = _mock_tenant_db_session(scalar_one_or_none=doc)

        try:
            with (
                patch(
                    "app.core.middleware.TenantResolver"
                ) as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        f"/api/v1/kb/documents/{doc_id}/reindex",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422
