"""CORS configuration security tests.

Verifies that the FastAPI CORSMiddleware is correctly configured to only
allow the back-office origin, not arbitrary domains.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


class TestCORSSecurity:
    """CORS must be restricted to the back-office origin."""

    @pytest.mark.asyncio
    async def test_cors_allows_configured_origin(self):
        """Preflight from backoffice_url gets Access-Control-Allow-Origin."""
        settings = get_settings()
        origin = settings.backoffice_url

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                "/api/v1/auth/login",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )

        assert response.headers.get("access-control-allow-origin") == origin

    @pytest.mark.asyncio
    async def test_cors_rejects_unknown_origin(self):
        """Preflight from evil.com does NOT get Access-Control-Allow-Origin."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                "/api/v1/auth/login",
                headers={
                    "Origin": "https://evil.com",
                    "Access-Control-Request-Method": "POST",
                },
            )

        acao = response.headers.get("access-control-allow-origin")
        assert acao != "https://evil.com"
        # Starlette CORSMiddleware either omits the header or returns 400
        assert acao is None or acao == ""

    @pytest.mark.asyncio
    async def test_cors_allows_credentials(self):
        """CORS response includes Access-Control-Allow-Credentials: true."""
        settings = get_settings()
        origin = settings.backoffice_url

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                "/api/v1/auth/login",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )

        assert response.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_cors_allows_required_headers(self):
        """CORS allows Content-Type, Authorization, and X-Tenant-ID headers."""
        settings = get_settings()
        origin = settings.backoffice_url

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                "/api/v1/auth/login",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type, Authorization, X-Tenant-ID",
                },
            )

        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert "content-type" in allowed
        assert "authorization" in allowed
        assert "x-tenant-id" in allowed

    @pytest.mark.asyncio
    async def test_cors_allows_required_methods(self):
        """CORS allows GET, POST, PATCH, DELETE methods."""
        settings = get_settings()
        origin = settings.backoffice_url

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                "/api/v1/auth/login",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "DELETE",
                },
            )

        allowed = response.headers.get("access-control-allow-methods", "").upper()
        for method in ["GET", "POST", "PATCH", "DELETE"]:
            assert method in allowed
