"""Tests for tenant CRUD API endpoints (/api/v1/tenants/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched services for provisioning/DB operations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import DuplicateTenantError
from app.core.rbac import get_current_admin
from app.main import app
from app.models.enums import AdminRole, TenantStatus
from app.schemas.auth import AdminTokenPayload

# --- Factories ---


def _make_super_admin_payload(**overrides) -> AdminTokenPayload:
    """Create a super_admin token payload."""
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": AdminRole.super_admin.value,
        "tenant_id": None,
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_tenant_admin_payload(
    tenant_id: uuid.UUID | None = None, **overrides
) -> AdminTokenPayload:
    """Create an admin_tenant token payload."""
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": AdminRole.admin_tenant.value,
        "tenant_id": str(tenant_id or uuid.uuid4()),
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_tenant_orm(**overrides) -> MagicMock:
    """Create a mock Tenant ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "CRI Rabat-Salé-Kénitra",
        "slug": "rabat",
        "region": "Rabat-Salé-Kénitra",
        "logo_url": None,
        "accent_color": None,
        "whatsapp_config": {
            "phone_number_id": "123456",
            "access_token": "secret-token",
            "verify_token": "verify-secret",
            "business_account_id": "biz-123",
        },
        "status": TenantStatus.active,
        "max_contacts": 20000,
        "max_messages_per_year": 100000,
        "max_admins": 10,
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_session_factory(result_value=None, scalar_value=None, scalars_value=None):
    """Create a mock session factory for tenant DB queries.

    Args:
        result_value: Value for result.scalar_one_or_none()
        scalar_value: Value for result.scalar_one()
        scalars_value: List for result.scalars().all()
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = result_value
    mock_result.scalar_one.return_value = scalar_value or result_value

    if scalars_value is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_value
        mock_result.scalars.return_value = mock_scalars

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory, mock_session


# --- Create tenant tests ---


class TestCreateTenantEndpoint:
    @pytest.mark.asyncio
    async def test_create_tenant_super_admin(self):
        """POST /tenants/ as super_admin returns 201."""
        payload = _make_super_admin_payload()
        tenant_orm = _make_tenant_orm()

        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            with patch("app.api.v1.tenant.TenantProvisioningService") as MockService:
                MockService.return_value.provision_tenant = AsyncMock(return_value=tenant_orm)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/tenants/",
                        json={
                            "name": "CRI Rabat-Salé-Kénitra",
                            "slug": "rabat",
                            "region": "Rabat-Salé-Kénitra",
                        },
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "CRI Rabat-Salé-Kénitra"
        assert data["slug"] == "rabat"
        assert data["status"] == "active"
        # TenantAdminResponse includes whatsapp_config
        assert "whatsapp_config" in data

    @pytest.mark.asyncio
    async def test_create_tenant_non_super_admin_forbidden(self):
        """POST /tenants/ as admin_tenant returns 403."""
        payload = _make_tenant_admin_payload()
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/tenants/",
                    json={
                        "name": "CRI Test",
                        "slug": "test-slug",
                        "region": "Test Region",
                    },
                    headers={"Authorization": "Bearer mock-token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_tenant_duplicate_slug(self):
        """POST /tenants/ with existing slug returns 409."""
        payload = _make_super_admin_payload()
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            with patch("app.api.v1.tenant.TenantProvisioningService") as MockService:
                MockService.return_value.provision_tenant = AsyncMock(
                    side_effect=DuplicateTenantError("rabat")
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/tenants/",
                        json={
                            "name": "CRI Duplicate",
                            "slug": "rabat",
                            "region": "Duplicate Region",
                        },
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 409
        assert "rabat" in response.json()["message"]

    @pytest.mark.asyncio
    async def test_create_tenant_unauthenticated(self):
        """POST /tenants/ without token returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/tenants/",
                json={
                    "name": "CRI Test",
                    "slug": "test-slug",
                    "region": "Test Region",
                },
            )

        assert response.status_code == 401


# --- List tenants tests ---


class TestListTenantsEndpoint:
    @pytest.mark.asyncio
    async def test_list_tenants_paginated(self):
        """GET /tenants/ as super_admin returns paginated list."""
        payload = _make_super_admin_payload()
        tenant1 = _make_tenant_orm(slug="rabat")
        tenant2 = _make_tenant_orm(slug="tanger")

        app.dependency_overrides[get_current_admin] = lambda: payload

        # Need two mock results: one for count, one for data query
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # First call returns count, second call returns tenants
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [tenant1, tenant2]
        data_result.scalars.return_value = mock_scalars

        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        mock_factory = MagicMock(return_value=mock_session)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/tenants/?page=1&page_size=10",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["items"]) == 2
        # TenantResponse — no whatsapp_config
        assert "whatsapp_config" not in data["items"][0]

    @pytest.mark.asyncio
    async def test_list_tenants_non_super_admin_forbidden(self):
        """GET /tenants/ as viewer returns 403."""
        payload = _make_tenant_admin_payload()
        payload_viewer = AdminTokenPayload(
            sub=payload.sub,
            role=AdminRole.viewer.value,
            tenant_id=payload.tenant_id,
            exp=payload.exp,
            iat=payload.iat,
            jti=payload.jti,
            type="access",
        )
        app.dependency_overrides[get_current_admin] = lambda: payload_viewer

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/tenants/",
                    headers={"Authorization": "Bearer mock-token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 403


# --- Get tenant tests ---


class TestGetTenantEndpoint:
    @pytest.mark.asyncio
    async def test_get_tenant_super_admin(self):
        """GET /tenants/{id} as super_admin returns TenantAdminResponse with whatsapp_config."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()
        tenant_orm = _make_tenant_orm(id=tenant_id)

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value=tenant_orm)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/tenants/{tenant_id}",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "rabat"
        # Super admin gets whatsapp_config
        assert "whatsapp_config" in data
        assert data["whatsapp_config"]["phone_number_id"] == "123456"

    @pytest.mark.asyncio
    async def test_get_tenant_own_admin(self):
        """GET /tenants/{id} as admin_tenant of that tenant returns TenantResponse (no secrets)."""
        tenant_id = uuid.uuid4()
        payload = _make_tenant_admin_payload(tenant_id=tenant_id)
        tenant_orm = _make_tenant_orm(id=tenant_id)

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value=tenant_orm)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/tenants/{tenant_id}",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "rabat"
        # Non-super_admin gets TenantResponse — no whatsapp_config
        assert "whatsapp_config" not in data

    @pytest.mark.asyncio
    async def test_get_other_tenant_forbidden(self):
        """GET /tenants/{id} as admin_tenant of different tenant returns 403."""
        tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()
        payload = _make_tenant_admin_payload(tenant_id=other_tenant_id)

        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    f"/api/v1/tenants/{tenant_id}",
                    headers={"Authorization": "Bearer mock-token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant(self):
        """GET /tenants/{id} for nonexistent tenant returns 404."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value=None)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/tenants/{tenant_id}",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 404


# --- Update tenant tests ---


class TestUpdateTenantEndpoint:
    @pytest.mark.asyncio
    async def test_update_tenant_partial(self):
        """PATCH /tenants/{id} with partial data updates only provided fields."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()
        tenant_orm = _make_tenant_orm(id=tenant_id, name="CRI Rabat Updated")

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tenant_orm
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.patch(
                        f"/api/v1/tenants/{tenant_id}",
                        json={"name": "CRI Rabat Updated"},
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 200
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent_tenant(self):
        """PATCH /tenants/{id} for nonexistent tenant returns 404."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value=None)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.patch(
                        f"/api/v1/tenants/{tenant_id}",
                        json={"name": "Updated"},
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 404


# --- Delete tenant tests ---


class TestDeleteTenantEndpoint:
    @pytest.mark.asyncio
    async def test_delete_tenant_success(self):
        """DELETE /tenants/{id} as super_admin returns 204."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value="rabat")

        try:
            with (
                patch(
                    "app.api.v1.tenant.get_session_factory",
                    return_value=mock_factory,
                ),
                patch("app.api.v1.tenant.TenantProvisioningService") as MockService,
            ):
                MockService.return_value.deprovision_tenant = AsyncMock()

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.delete(
                        f"/api/v1/tenants/{tenant_id}",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_tenant(self):
        """DELETE /tenants/{id} for nonexistent tenant returns 404."""
        tenant_id = uuid.uuid4()
        payload = _make_super_admin_payload()

        app.dependency_overrides[get_current_admin] = lambda: payload

        mock_factory, _ = _mock_session_factory(result_value=None)

        try:
            with patch(
                "app.api.v1.tenant.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.delete(
                        f"/api/v1/tenants/{tenant_id}",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 404
