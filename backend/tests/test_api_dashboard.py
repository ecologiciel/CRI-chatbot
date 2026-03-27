"""Tests for Dashboard API endpoints (/api/v1/dashboard/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched TenantResolver for middleware bypass.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole
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


def _setup_overrides(role: str = AdminRole.admin_tenant.value) -> AdminTokenPayload:
    payload = _make_admin_payload(role=role)
    app.dependency_overrides[get_current_admin] = lambda: payload
    return payload


def _clear_overrides():
    app.dependency_overrides.pop(get_current_admin, None)


def _headers() -> dict:
    return {
        "Authorization": "Bearer mock-token",
        "X-Tenant-ID": str(TEST_TENANT.id),
    }


MOCK_STATS = {
    "active_conversations": 12,
    "messages_today": 87,
    "resolution_rate": 82.5,
    "csat_score": 3.8,
    "total_contacts": 150,
    "kb_documents_indexed": 25,
    "unanswered_questions": 7,
    "quota_usage": None,
}


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------


class TestDashboardStats:
    @pytest.mark.asyncio
    async def test_stats_success(self):
        """GET /dashboard/stats returns all KPIs."""
        _setup_overrides()

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dashboard.get_dashboard_service"
                ) as mock_svc,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_service = MagicMock()
                mock_service.get_stats = AsyncMock(return_value=MOCK_STATS)
                mock_svc.return_value = mock_service

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/dashboard/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["active_conversations"] == 12
        assert data["messages_today"] == 87
        assert data["resolution_rate"] == 82.5
        assert data["csat_score"] == 3.8
        assert data["total_contacts"] == 150
        assert data["kb_documents_indexed"] == 25
        assert data["unanswered_questions"] == 7

    @pytest.mark.asyncio
    async def test_stats_viewer_allowed(self):
        """GET /dashboard/stats with viewer role returns 200."""
        _setup_overrides(role=AdminRole.viewer.value)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dashboard.get_dashboard_service"
                ) as mock_svc,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_service = MagicMock()
                mock_service.get_stats = AsyncMock(return_value=MOCK_STATS)
                mock_svc.return_value = mock_service

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/dashboard/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_fields_types(self):
        """GET /dashboard/stats returns correct types for all fields."""
        _setup_overrides()

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dashboard.get_dashboard_service"
                ) as mock_svc,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_service = MagicMock()
                mock_service.get_stats = AsyncMock(return_value=MOCK_STATS)
                mock_svc.return_value = mock_service

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/dashboard/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        data = response.json()
        assert isinstance(data["active_conversations"], int)
        assert isinstance(data["messages_today"], int)
        assert isinstance(data["resolution_rate"], (int, float))
        assert isinstance(data["csat_score"], (int, float))
        assert isinstance(data["total_contacts"], int)
        assert isinstance(data["kb_documents_indexed"], int)
        assert isinstance(data["unanswered_questions"], int)
