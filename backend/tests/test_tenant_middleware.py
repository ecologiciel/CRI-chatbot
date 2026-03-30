"""Tests for TenantMiddleware, TenantContext, and get_current_tenant."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import TenantInactiveError, TenantNotFoundError
from app.core.tenant import TenantContext
from app.main import app

# --- Fixtures ---

TEST_TENANT_ID = uuid.uuid4()


def _make_tenant_context(**overrides) -> TenantContext:
    """Create a TenantContext with sensible defaults."""
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat-Salé-Kénitra",
        "status": "active",
        "whatsapp_config": {"phone_number_id": "123456"},
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


# --- TenantContext unit tests ---


class TestTenantContext:
    def test_properties(self):
        """Computed properties should follow naming conventions."""
        ctx = _make_tenant_context(slug="rabat")
        assert ctx.db_schema == "tenant_rabat"
        assert ctx.qdrant_collection == "kb_rabat"
        assert ctx.redis_prefix == "rabat"
        assert ctx.minio_bucket == "cri-rabat"

    def test_slug_validation_rejects_invalid(self):
        """Invalid slugs (SQL injection risk) should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            _make_tenant_context(slug="rabat; DROP TABLE tenants;--")

    def test_slug_validation_accepts_valid(self):
        """Valid slugs with letters, numbers, and underscores should work."""
        ctx = _make_tenant_context(slug="rabat_sale_kenitra")
        assert ctx.slug == "rabat_sale_kenitra"

    @pytest.mark.asyncio
    async def test_db_session_sets_search_path(self):
        """db_session() should SET search_path to the tenant's schema."""
        ctx = _make_tenant_context(slug="tanger")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.core.tenant.get_session_factory", return_value=mock_factory):
            async with ctx.db_session() as session:
                assert session is mock_session

        # Verify SET search_path was called
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args[0][0]
        assert "tenant_tanger" in str(call_args)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_session_rollback_on_error(self):
        """db_session() should rollback on exception."""
        ctx = _make_tenant_context(slug="rabat")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with (
            patch("app.core.tenant.get_session_factory", return_value=mock_factory),
            pytest.raises(RuntimeError, match="test error"),
        ):
            async with ctx.db_session():
                raise RuntimeError("test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()


# --- Middleware integration tests ---


class TestTenantMiddleware:
    """Tests using httpx AsyncClient against the real FastAPI app."""

    @pytest.mark.asyncio
    async def test_excluded_paths_bypass_middleware(self):
        """Health endpoint should work without X-Tenant-ID."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health")
        # Health check may return 200 or 503 depending on infra,
        # but it should NOT return 400 for missing tenant header
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_missing_tenant_header_returns_400(self):
        """Non-excluded routes without X-Tenant-ID should get 400."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/some-route")
        assert response.status_code == 400
        assert "X-Tenant-ID header is required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_tenant_header_resolves(self):
        """Valid X-Tenant-ID should resolve tenant and pass through."""
        tenant_ctx = _make_tenant_context()

        with patch(
            "app.core.middleware.TenantResolver.from_tenant_id_header",
            new_callable=AsyncMock,
            return_value=tenant_ctx,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/health",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                )
        # Health check should proceed normally with tenant resolved
        assert response.status_code != 400
        assert response.status_code != 403
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_returns_404(self):
        """Non-existent tenant UUID should return 404."""
        fake_id = str(uuid.uuid4())

        with patch(
            "app.core.middleware.TenantResolver.from_tenant_id_header",
            new_callable=AsyncMock,
            side_effect=TenantNotFoundError(
                f"Tenant not found: {fake_id}",
                details={"identifier": fake_id},
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/some-route",
                    headers={"X-Tenant-ID": fake_id},
                )
        assert response.status_code == 404
        assert "Tenant not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_inactive_tenant_returns_403(self):
        """Inactive tenant should return 403."""
        with patch(
            "app.core.middleware.TenantResolver.from_tenant_id_header",
            new_callable=AsyncMock,
            side_effect=TenantInactiveError(
                "Tenant is not active: rabat",
                details={"slug": "rabat", "status": "inactive"},
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/some-route",
                    headers={"X-Tenant-ID": str(TEST_TENANT_ID)},
                )
        assert response.status_code == 403
        assert "not active" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_webhook_path_excluded(self):
        """Webhook paths should pass without X-Tenant-ID."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/webhook/whatsapp")
        # Should NOT be 400 — webhook paths are excluded from middleware
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_docs_path_excluded(self):
        """Docs path should be accessible without X-Tenant-ID."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/docs")
        assert response.status_code != 400
