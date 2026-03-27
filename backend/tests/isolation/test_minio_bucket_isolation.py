"""MinIO bucket isolation tests.

Verifies that each tenant's files are stored in a dedicated bucket,
and that KB operations use the correct tenant bucket.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext, get_current_tenant
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload

from .conftest import make_tenant


# --- Helpers ---

def _make_admin_payload(role: str = AdminRole.admin_tenant.value) -> AdminTokenPayload:
    return AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=role,
        tenant_id=str(uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )


def _make_document_orm(doc_id=None, file_path="docs/test.pdf"):
    mock = MagicMock()
    mock.id = doc_id or uuid.uuid4()
    mock.title = "Test Doc"
    mock.source_url = None
    mock.file_path = file_path
    mock.category = "general"
    mock.language = "fr"
    mock.content_hash = "abc123"
    mock.status = "indexed"
    mock.error_message = None
    mock.chunk_count = 5
    mock.created_at = "2025-01-01T00:00:00Z"
    mock.updated_at = "2025-01-01T00:00:00Z"
    mock.chunks = []
    return mock


class TestMinioBucketIsolation:
    """MinIO buckets must be strictly per-tenant."""

    def test_bucket_name_format(self, tenant_alpha, tenant_beta):
        """Bucket names follow the cri-{slug} pattern."""
        assert tenant_alpha.minio_bucket == "cri-alpha"
        assert tenant_beta.minio_bucket == "cri-beta"

    def test_no_bucket_overlap(self):
        """Multiple tenants produce unique bucket names."""
        slugs = ["rabat", "tanger", "casa", "marrakech"]
        buckets = {make_tenant(s).minio_bucket for s in slugs}
        assert len(buckets) == 4
        assert buckets == {"cri-rabat", "cri-tanger", "cri-casa", "cri-marrakech"}

    @pytest.mark.asyncio
    async def test_kb_upload_uses_tenant_bucket(self, tenant_alpha):
        """POST /kb/documents stores files in the tenant's MinIO bucket."""
        from datetime import datetime, timezone

        mock_minio = MagicMock()
        mock_minio.put_object = AsyncMock()

        def _refresh_doc(obj):
            """Simulate DB refresh setting server defaults."""
            obj.id = obj.id or uuid.uuid4()
            obj.chunk_count = 0
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.error_message = None
            obj.source_url = None
            obj.content_hash = None

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=_refresh_doc)
        mock_session.add = MagicMock()

        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)

        app.dependency_overrides[get_current_admin] = lambda: payload
        app.dependency_overrides[get_current_tenant] = lambda: tenant_alpha

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
                patch("app.api.v1.kb.get_minio", return_value=mock_minio),
                patch("app.api.v1.kb.get_arq_pool", return_value=AsyncMock()),
                patch("app.api.v1.kb.get_settings") as mock_settings,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=tenant_alpha)
                mock_settings.return_value = MagicMock(kb_max_file_size_bytes=10 * 1024 * 1024)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(tenant_alpha.id)},
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        data={"title": "Test", "language": "fr"},
                        files={"file": ("test.pdf", b"%PDF-1.4 test content", "application/pdf")},
                    )

            assert response.status_code == 202
            # The endpoint called put_object with the tenant bucket
            mock_minio.put_object.assert_called_once()
            call_kwargs = mock_minio.put_object.call_args
            assert call_kwargs.kwargs.get("bucket_name") == "cri-alpha"
        finally:
            app.dependency_overrides.pop(get_current_admin, None)
            app.dependency_overrides.pop(get_current_tenant, None)

    @pytest.mark.asyncio
    async def test_kb_delete_uses_tenant_bucket(self, tenant_alpha):
        """DELETE /kb/documents/{id} removes files from the tenant's MinIO bucket."""
        doc_id = uuid.uuid4()
        mock_doc = _make_document_orm(doc_id=doc_id)

        mock_minio = MagicMock()
        mock_minio.remove_object = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)

        app.dependency_overrides[get_current_admin] = lambda: payload
        app.dependency_overrides[get_current_tenant] = lambda: tenant_alpha

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
                patch("app.api.v1.kb.get_minio", return_value=mock_minio),
                patch("app.services.rag.ingestion.get_ingestion_service") as mock_get_ingestion,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=tenant_alpha)
                mock_ingestion = AsyncMock()
                mock_ingestion.delete_document = AsyncMock()
                mock_get_ingestion.return_value = mock_ingestion

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(tenant_alpha.id)},
                ) as client:
                    response = await client.delete(f"/api/v1/kb/documents/{doc_id}")

            assert response.status_code == 204
            # remove_object is called with positional args: (bucket, path)
            mock_minio.remove_object.assert_called_once()
            bucket_arg = mock_minio.remove_object.call_args[0][0]
            assert bucket_arg == "cri-alpha"
        finally:
            app.dependency_overrides.pop(get_current_admin, None)
            app.dependency_overrides.pop(get_current_tenant, None)
