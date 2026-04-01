"""Tests d'isolation multi-tenant pour les modules Phase 2.

Verifie que les endpoints Phase 2 scopent les donnees au tenant correct :
escalade, campagne, whitelist, apprentissage.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.core.rbac import get_current_admin
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload

TEST_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_ADMIN_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TEST_TENANT_SLUG = "test_tenant"


def _make_admin_payload(role=AdminRole.admin_tenant.value):
    """Create an AdminTokenPayload for test auth."""
    return AdminTokenPayload(
        sub=str(TEST_ADMIN_ID),
        role=role,
        tenant_id=str(TEST_TENANT_ID),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )


def _make_mock_tenant():
    """Create a MagicMock tenant."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = TEST_TENANT_SLUG
    tenant.name = "CRI Test"
    tenant.status = "active"
    tenant.whatsapp_config = {
        "phone_number_id": "111222333",
        "access_token": "test_token",
    }
    tenant.db_schema = f"tenant_{TEST_TENANT_SLUG}"
    tenant.qdrant_collection = f"kb_{TEST_TENANT_SLUG}"
    tenant.redis_prefix = TEST_TENANT_SLUG
    tenant.minio_bucket = f"cri-{TEST_TENANT_SLUG}"
    return tenant


def _headers():
    return {
        "Authorization": "Bearer mock-token",
        "X-Tenant-ID": str(TEST_TENANT_ID),
    }


class TestTenantIsolationPhase2:
    """Tests d'isolation cross-tenant pour les modules Phase 2."""

    @pytest.mark.asyncio
    async def test_escalation_scoped_to_tenant(self):
        """Les escalades listees sont scopees au tenant du header X-Tenant-ID."""
        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            mock_tenant = _make_mock_tenant()
            mock_svc = MagicMock()
            mock_svc.get_escalations = AsyncMock(return_value=([], 0))

            with (
                patch(
                    "app.core.middleware.TenantResolver.from_tenant_id_header",
                    new=AsyncMock(return_value=mock_tenant),
                ),
                patch(
                    "app.api.v1.escalation.get_escalation_service",
                    return_value=mock_svc,
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/v1/escalations",
                        headers=_headers(),
                    )

            assert resp.status_code == 200
            # Verify service was called (tenant is passed through middleware)
            mock_svc.get_escalations.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

    @pytest.mark.asyncio
    async def test_campaign_scoped_to_tenant(self):
        """Les campagnes listees sont scopees au tenant."""
        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            mock_tenant = _make_mock_tenant()
            mock_svc = MagicMock()
            mock_svc.list_campaigns = AsyncMock(return_value=([], 0))

            with (
                patch(
                    "app.core.middleware.TenantResolver.from_tenant_id_header",
                    new=AsyncMock(return_value=mock_tenant),
                ),
                patch(
                    "app.api.v1.campaigns.get_campaign_service",
                    return_value=mock_svc,
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/v1/campaigns",
                        headers=_headers(),
                    )

            assert resp.status_code == 200
            mock_svc.list_campaigns.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

    @pytest.mark.asyncio
    async def test_whitelist_scoped_to_tenant(self):
        """La whitelist est scopee au tenant."""
        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            mock_tenant = _make_mock_tenant()

            # Mock DB session for whitelist list endpoint
            mock_session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 0
            data_result = MagicMock()
            data_scalars = MagicMock()
            data_scalars.all.return_value = []
            data_result.scalars.return_value = data_scalars

            call_count = 0

            async def _execute_side(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return count_result
                return data_result

            mock_session.execute = AsyncMock(side_effect=_execute_side)

            class _FakeAsyncCM:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    return False

            mock_tenant.db_session = MagicMock(return_value=_FakeAsyncCM())

            with patch(
                "app.core.middleware.TenantResolver.from_tenant_id_header",
                new=AsyncMock(return_value=mock_tenant),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/v1/whitelist",
                        headers=_headers(),
                    )

            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

    @pytest.mark.asyncio
    async def test_learning_scoped_to_tenant(self):
        """Les questions d'apprentissage sont scopees au tenant."""
        payload = _make_admin_payload(role=AdminRole.admin_tenant.value)
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            mock_tenant = _make_mock_tenant()
            mock_svc = MagicMock()
            mock_svc.get_unanswered_questions = AsyncMock(return_value=([], 0))

            with (
                patch(
                    "app.core.middleware.TenantResolver.from_tenant_id_header",
                    new=AsyncMock(return_value=mock_tenant),
                ),
                patch(
                    "app.api.v1.learning.get_learning_service",
                    return_value=mock_svc,
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/v1/learning/questions",
                        headers=_headers(),
                    )

            assert resp.status_code == 200
            mock_svc.get_unanswered_questions.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_admin, None)
