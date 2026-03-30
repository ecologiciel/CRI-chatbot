"""Systematic RBAC matrix tests.

Verifies the full role-based access control matrix across all protected
endpoints. Each role is tested against each endpoint category.
"""

import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext, get_current_tenant
from app.main import app
from app.models.enums import AdminRole

from .conftest import (
    OTHER_TENANT_ID,
    TEST_TENANT_ID,
    make_admin_payload,
    mock_tenant_db_session,
    override_admin,
)

# --- Helpers ---


def _make_tenant() -> TenantContext:
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="alpha",
        name="CRI Alpha",
        status="active",
        whatsapp_config={"phone_number_id": "111"},
    )


def _make_tenant_orm(**overrides):
    """Mock Tenant ORM object for tenant endpoints."""
    defaults = {
        "id": TEST_TENANT_ID,
        "name": "CRI Alpha",
        "slug": "alpha",
        "region": "RSK",
        "logo_url": None,
        "accent_color": None,
        "whatsapp_config": {
            "phone_number_id": "111",
            "access_token": "test_token",
            "verify_token": "test_verify",
        },
        "status": "active",
        "max_contacts": 20000,
        "max_messages_per_year": 100000,
        "max_admins": 10,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_doc_orm():
    """Mock KBDocument ORM for KB endpoints."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.title = "Test"
    mock.source_url = None
    mock.file_path = "docs/test.pdf"
    mock.category = "general"
    mock.language = "fr"
    mock.content_hash = "abc"
    mock.status = "indexed"
    mock.error_message = None
    mock.chunk_count = 0
    mock.created_at = "2025-01-01T00:00:00Z"
    mock.updated_at = "2025-01-01T00:00:00Z"
    mock.chunks = []
    return mock


def _mock_session_for_list(items=None, total=0):
    """Create mock session for paginated list endpoints."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    async def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Count query
            result.scalar_one.return_value = total
        else:
            # Data query
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = items or []
            result.scalars.return_value = mock_scalars
        return result

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    session.commit = AsyncMock()
    return session


# --- Tenant Endpoint RBAC ---


class TestTenantEndpointRBAC:
    """RBAC for /api/v1/tenants/ endpoints (super_admin only)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 201),
            (AdminRole.admin_tenant, 403),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_create_tenant_rbac(self, role, expected_status):
        """POST /tenants/ — only super_admin gets 201."""
        payload = make_admin_payload(
            role=role.value, tenant_id=None if role == AdminRole.super_admin else TEST_TENANT_ID
        )
        cleanup = override_admin(payload)
        try:
            with patch("app.api.v1.tenant.TenantProvisioningService") as MockProv:
                mock_prov = AsyncMock()
                mock_prov.provision_tenant = AsyncMock(return_value=_make_tenant_orm())
                MockProv.return_value = mock_prov

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/tenants/",
                        json={"name": "New CRI", "slug": "newcri", "region": "RSK"},
                    )

            assert response.status_code == expected_status
        finally:
            cleanup()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 200),
            (AdminRole.admin_tenant, 403),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_list_tenants_rbac(self, role, expected_status):
        """GET /tenants/ — only super_admin gets 200."""
        payload = make_admin_payload(
            role=role.value, tenant_id=None if role == AdminRole.super_admin else TEST_TENANT_ID
        )
        cleanup = override_admin(payload)
        try:
            mock_session = _mock_session_for_list(items=[], total=0)
            mock_factory = MagicMock(return_value=mock_session)

            with patch("app.api.v1.tenant.get_session_factory", return_value=mock_factory):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/api/v1/tenants/")

            assert response.status_code == expected_status
        finally:
            cleanup()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 200),
            (AdminRole.admin_tenant, 403),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_update_tenant_rbac(self, role, expected_status):
        """PATCH /tenants/{id} — only super_admin gets 200."""
        payload = make_admin_payload(
            role=role.value, tenant_id=None if role == AdminRole.super_admin else TEST_TENANT_ID
        )
        cleanup = override_admin(payload)
        try:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = _make_tenant_orm()
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()
            mock_factory = MagicMock(return_value=mock_session)

            with patch("app.api.v1.tenant.get_session_factory", return_value=mock_factory):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.patch(
                        f"/api/v1/tenants/{TEST_TENANT_ID}",
                        json={"name": "Updated"},
                    )

            assert response.status_code == expected_status
        finally:
            cleanup()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 204),
            (AdminRole.admin_tenant, 403),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_delete_tenant_rbac(self, role, expected_status):
        """DELETE /tenants/{id} — only super_admin gets 204."""
        payload = make_admin_payload(
            role=role.value, tenant_id=None if role == AdminRole.super_admin else TEST_TENANT_ID
        )
        cleanup = override_admin(payload)
        try:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = _make_tenant_orm()
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_factory = MagicMock(return_value=mock_session)

            with (
                patch("app.api.v1.tenant.get_session_factory", return_value=mock_factory),
                patch("app.api.v1.tenant.TenantProvisioningService") as MockProv,
            ):
                mock_prov = AsyncMock()
                mock_prov.deprovision_tenant = AsyncMock()
                MockProv.return_value = mock_prov

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.delete(f"/api/v1/tenants/{TEST_TENANT_ID}")

            assert response.status_code == expected_status
        finally:
            cleanup()


# --- KB Endpoint RBAC ---


class TestKBEndpointRBAC:
    """RBAC for /api/v1/kb/ endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 202),
            (AdminRole.admin_tenant, 202),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_kb_upload_rbac(self, role, expected_status, test_tenant):
        """POST /kb/documents — super_admin + admin_tenant get 202."""
        from datetime import datetime

        payload = make_admin_payload(role=role.value)
        cleanup = override_admin(payload)
        app.dependency_overrides[get_current_tenant] = lambda: test_tenant

        def _refresh_doc(obj):
            obj.id = obj.id or uuid.uuid4()
            obj.chunk_count = 0
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)
            obj.error_message = None
            obj.source_url = None
            obj.content_hash = None

        try:
            mock_session = mock_tenant_db_session()
            mock_session.refresh = AsyncMock(side_effect=_refresh_doc)
            mock_minio = MagicMock()
            mock_minio.put_object = AsyncMock()

            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
                patch("app.api.v1.kb.get_minio", return_value=mock_minio),
                patch("app.api.v1.kb.get_arq_pool", return_value=AsyncMock()),
                patch("app.api.v1.kb.get_settings") as mock_settings,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=test_tenant)
                mock_settings.return_value = MagicMock(kb_max_file_size_bytes=10 * 1024 * 1024)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                ) as client:
                    response = await client.post(
                        "/api/v1/kb/documents",
                        data={"title": "Test", "language": "fr"},
                        files={"file": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
                    )

            assert response.status_code == expected_status
        finally:
            cleanup()
            app.dependency_overrides.pop(get_current_tenant, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 200),
            (AdminRole.admin_tenant, 200),
            (AdminRole.supervisor, 200),
            (AdminRole.viewer, 200),
        ],
    )
    async def test_kb_list_rbac(self, role, expected_status, test_tenant):
        """GET /kb/documents — all roles get 200."""
        payload = make_admin_payload(role=role.value)
        cleanup = override_admin(payload)
        app.dependency_overrides[get_current_tenant] = lambda: test_tenant
        try:
            mock_session = _mock_session_for_list(items=[], total=0)

            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=test_tenant)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                ) as client:
                    response = await client.get("/api/v1/kb/documents")

            assert response.status_code == expected_status
        finally:
            cleanup()
            app.dependency_overrides.pop(get_current_tenant, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 204),
            (AdminRole.admin_tenant, 204),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_kb_delete_rbac(self, role, expected_status, test_tenant):
        """DELETE /kb/documents/{id} — super_admin + admin_tenant get 204."""
        doc_id = uuid.uuid4()
        payload = make_admin_payload(role=role.value)
        cleanup = override_admin(payload)
        app.dependency_overrides[get_current_tenant] = lambda: test_tenant
        try:
            mock_doc = _make_doc_orm()
            mock_session = mock_tenant_db_session(scalar_one_or_none=mock_doc)

            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
                patch("app.api.v1.kb.get_minio", return_value=MagicMock(remove_object=AsyncMock())),
                patch("app.services.rag.ingestion.get_ingestion_service") as mock_get_ingestion,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=test_tenant)
                mock_ingestion = AsyncMock()
                mock_ingestion.delete_document = AsyncMock()
                mock_get_ingestion.return_value = mock_ingestion

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                ) as client:
                    response = await client.delete(f"/api/v1/kb/documents/{doc_id}")

            assert response.status_code == expected_status
        finally:
            cleanup()
            app.dependency_overrides.pop(get_current_tenant, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (AdminRole.super_admin, 202),
            (AdminRole.admin_tenant, 202),
            (AdminRole.supervisor, 403),
            (AdminRole.viewer, 403),
        ],
    )
    async def test_kb_reindex_rbac(self, role, expected_status, test_tenant):
        """POST /kb/documents/{id}/reindex — super_admin + admin_tenant get 202."""
        doc_id = uuid.uuid4()
        payload = make_admin_payload(role=role.value)
        cleanup = override_admin(payload)
        app.dependency_overrides[get_current_tenant] = lambda: test_tenant
        try:
            mock_doc = _make_doc_orm()
            mock_session = mock_tenant_db_session(scalar_one_or_none=mock_doc)

            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
                patch("app.api.v1.kb.get_arq_pool", return_value=AsyncMock()),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=test_tenant)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                ) as client:
                    response = await client.post(f"/api/v1/kb/documents/{doc_id}/reindex")

            assert response.status_code == expected_status
        finally:
            cleanup()
            app.dependency_overrides.pop(get_current_tenant, None)


# --- Auth Endpoint RBAC ---


class TestAuthEndpointRBAC:
    """RBAC for /api/v1/auth/ endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role",
        [
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        ],
    )
    async def test_auth_me_all_roles(self, role):
        """GET /auth/me — all authenticated roles get 200."""
        admin_id = uuid.uuid4()
        payload = make_admin_payload(role=role.value, admin_id=admin_id)
        cleanup = override_admin(payload)
        try:
            mock_admin = MagicMock()
            mock_admin.id = admin_id
            mock_admin.email = "test@cri.ma"
            mock_admin.full_name = "Test Admin"
            mock_admin.role = role
            mock_admin.tenant_id = TEST_TENANT_ID
            mock_admin.is_active = True
            mock_admin.last_login = None
            mock_admin.created_at = "2025-01-01T00:00:00Z"
            mock_admin.updated_at = "2025-01-01T00:00:00Z"

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_admin
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_factory = MagicMock(return_value=mock_session)

            with patch("app.api.v1.auth.get_session_factory", return_value=mock_factory):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/api/v1/auth/me")

            assert response.status_code == 200
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_auth_me_unauthenticated(self):
        """GET /auth/me without Bearer token returns 401."""
        # Ensure no overrides
        app.dependency_overrides.pop(get_current_admin, None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401


# --- Cross-Tenant Access Control ---


class TestCrossTenantAccess:
    """Verify that admin_tenant cannot access other tenants' data."""

    @pytest.mark.asyncio
    async def test_admin_tenant_own_tenant_ok(self):
        """admin_tenant can GET their own tenant."""
        payload = make_admin_payload(
            role=AdminRole.admin_tenant.value,
            tenant_id=TEST_TENANT_ID,
        )
        cleanup = override_admin(payload)
        try:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = _make_tenant_orm(id=TEST_TENANT_ID)
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_factory = MagicMock(return_value=mock_session)

            with patch("app.api.v1.tenant.get_session_factory", return_value=mock_factory):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(f"/api/v1/tenants/{TEST_TENANT_ID}")

            assert response.status_code == 200
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_admin_tenant_other_tenant_denied(self):
        """admin_tenant cannot GET another tenant's data."""
        payload = make_admin_payload(
            role=AdminRole.admin_tenant.value,
            tenant_id=TEST_TENANT_ID,
        )
        cleanup = override_admin(payload)
        try:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = _make_tenant_orm(id=OTHER_TENANT_ID)
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_factory = MagicMock(return_value=mock_session)

            with patch("app.api.v1.tenant.get_session_factory", return_value=mock_factory):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(f"/api/v1/tenants/{OTHER_TENANT_ID}")

            assert response.status_code == 403
        finally:
            cleanup()
