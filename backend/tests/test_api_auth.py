"""Tests for authentication API endpoints (/api/v1/auth/).

Uses httpx AsyncClient with mocked services.
Login/refresh: patch AuthService methods.
Me/logout: override get_current_admin dependency.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AccountLockedError, AuthenticationError
from app.core.rbac import get_current_admin
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload, AuthTokenResponse

# --- Factories ---


def _make_token_payload(**overrides) -> AdminTokenPayload:
    """Create a mock AdminTokenPayload."""
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": AdminRole.admin_tenant.value,
        "tenant_id": str(uuid.uuid4()),
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_token_response() -> AuthTokenResponse:
    """Create a mock AuthTokenResponse."""
    return AuthTokenResponse(
        access_token="mock-access-token",
        refresh_token="mock-refresh-token",
        token_type="bearer",
        expires_in=1800,
    )


def _make_admin_orm(**overrides) -> MagicMock:
    """Create a mock Admin ORM object for /me endpoint."""
    admin_id = overrides.pop("id", uuid.uuid4())
    tenant_id = overrides.pop("tenant_id", uuid.uuid4())
    defaults = {
        "id": admin_id,
        "email": "admin@cri-rabat.ma",
        "full_name": "Admin CRI Rabat",
        "role": AdminRole.admin_tenant,
        "tenant_id": tenant_id,
        "is_active": True,
        "last_login": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


# --- Login tests ---


class TestLoginEndpoint:
    @pytest.mark.asyncio
    async def test_login_success(self):
        """POST /auth/login with valid credentials returns 200 + tokens."""
        mock_response = _make_token_response()

        with patch("app.api.v1.auth.AuthService") as MockAuthService:
            MockAuthService.return_value.login = AsyncMock(return_value=mock_response)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "admin@cri-rabat.ma", "password": "SecureP@ss123!"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "mock-access-token"
        assert data["refresh_token"] == "mock-refresh-token"
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 1800

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        """POST /auth/login with wrong password returns 401."""
        with patch("app.api.v1.auth.AuthService") as MockAuthService:
            MockAuthService.return_value.login = AsyncMock(
                side_effect=AuthenticationError("Invalid credentials")
            )

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "admin@cri-rabat.ma", "password": "wrong"},
                )

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["message"]

    @pytest.mark.asyncio
    async def test_login_locked_account(self):
        """POST /auth/login when locked returns 429."""
        with patch("app.api.v1.auth.AuthService") as MockAuthService:
            MockAuthService.return_value.login = AsyncMock(
                side_effect=AccountLockedError(remaining_seconds=1500)
            )

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "admin@cri-rabat.ma", "password": "any"},
                )

        assert response.status_code == 429
        assert response.json()["details"]["remaining_seconds"] == 1500

    @pytest.mark.asyncio
    async def test_login_missing_fields(self):
        """POST /auth/login with empty body returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/auth/login", json={})

        assert response.status_code == 422


# --- Refresh tests ---


class TestRefreshEndpoint:
    @pytest.mark.asyncio
    async def test_refresh_success(self):
        """POST /auth/refresh with valid token returns 200 + new tokens."""
        mock_response = _make_token_response()

        with patch("app.api.v1.auth.AuthService") as MockAuthService:
            MockAuthService.return_value.refresh_token = AsyncMock(return_value=mock_response)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": "some-refresh-token"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "mock-access-token"
        assert data["refresh_token"] == "mock-refresh-token"

    @pytest.mark.asyncio
    async def test_refresh_reuse_fails(self):
        """POST /auth/refresh with already-used token returns 401."""
        with patch("app.api.v1.auth.AuthService") as MockAuthService:
            MockAuthService.return_value.refresh_token = AsyncMock(
                side_effect=AuthenticationError("Refresh token already used")
            )

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": "used-token"},
                )

        assert response.status_code == 401
        assert "already used" in response.json()["message"]


# --- Me tests ---


class TestMeEndpoint:
    @pytest.mark.asyncio
    async def test_me_authenticated(self):
        """GET /auth/me with valid JWT returns 200 + admin profile."""
        admin_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        payload = _make_token_payload(sub=str(admin_id), tenant_id=str(tenant_id))
        admin_orm = _make_admin_orm(id=admin_id, tenant_id=tenant_id)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_orm
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(return_value=mock_session)

        # Override get_current_admin to skip real JWT verification
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            with patch(
                "app.api.v1.auth.get_session_factory",
                return_value=mock_factory,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/auth/me",
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "admin@cri-rabat.ma"
        assert data["full_name"] == "Admin CRI Rabat"
        assert data["role"] == "admin_tenant"
        assert "password_hash" not in data

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self):
        """GET /auth/me without token returns 401."""
        # No dependency override → real get_current_admin runs → fails
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401


# --- Logout tests ---


class TestLogoutEndpoint:
    @pytest.mark.asyncio
    async def test_logout_success(self):
        """POST /auth/logout with valid tokens returns 204."""
        payload = _make_token_payload()
        refresh_jti = str(uuid.uuid4())

        # Override get_current_admin
        app.dependency_overrides[get_current_admin] = lambda: payload

        try:
            with (
                patch(
                    "app.api.v1.auth.JWTManager.verify_token",
                    return_value={"type": "refresh", "jti": refresh_jti, "sub": payload.sub},
                ),
                patch("app.api.v1.auth.AuthService") as MockAuthService,
            ):
                MockAuthService.return_value.logout = AsyncMock()

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/auth/logout",
                        json={"refresh_token": "some-refresh-token"},
                        headers={"Authorization": "Bearer mock-token"},
                    )
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_logout_without_bearer(self):
        """POST /auth/logout without Bearer token returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "some-token"},
            )

        assert response.status_code == 401
