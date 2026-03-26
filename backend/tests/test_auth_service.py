"""Tests for AuthService and JWTManager — login, refresh, rate limiting."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AccountLockedError, AuthenticationError
from app.models.enums import AdminRole
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService


# --- Factories ---


def _make_admin_orm(**overrides):
    """Create a mock Admin ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "email": "admin@cri-rabat.ma",
        "password_hash": AuthService.hash_password("SecureP@ss123!"),
        "full_name": "Admin CRI",
        "role": AdminRole.admin_tenant,
        "tenant_id": uuid.uuid4(),
        "is_active": True,
        "last_login": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_session_factory(admin=None):
    """Create a mock session factory that returns admin on query."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin
    mock_result.scalar_one.return_value = admin

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory, mock_session


# --- Password hashing tests ---


class TestPasswordHashing:
    def test_password_hash_and_verify(self):
        """Bcrypt hash + verify round-trip should work."""
        password = "MySecure@Pass42!"
        hashed = AuthService.hash_password(password)

        # Hash should not be the plaintext
        assert hashed != password
        # Hash should start with bcrypt prefix
        assert hashed.startswith("$2b$")

        # Verify should succeed with correct password
        assert AuthService.verify_password(password, hashed) is True

        # Verify should fail with wrong password
        assert AuthService.verify_password("wrong", hashed) is False

    def test_bcrypt_cost_factor(self):
        """Hash should use cost factor 12."""
        hashed = AuthService.hash_password("TestPass123!")
        # bcrypt hash format: $2b$12$...
        assert "$2b$12$" in hashed


# --- Login tests ---


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self):
        """Valid credentials should return tokens and update last_login."""
        admin = _make_admin_orm()
        mock_factory, mock_session = _mock_session_factory(admin=admin)
        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)  # No lockout

        with (
            patch("app.services.auth.service.get_session_factory", return_value=mock_factory),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
            patch("app.services.auth.jwt.get_settings") as mock_settings,
            patch("app.services.auth.jwt.get_redis", return_value=mock_redis),
            patch("app.services.auth.service.get_settings") as mock_svc_settings,
        ):
            mock_settings.return_value = MagicMock(
                jwt_secret_key="test-secret",
                jwt_algorithm="HS256",
                jwt_access_token_expire_minutes=30,
                jwt_refresh_token_expire_days=7,
            )
            mock_svc_settings.return_value = mock_settings.return_value

            service = AuthService()
            result = await service.login("admin@cri-rabat.ma", "SecureP@ss123!")

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"
        assert result.expires_in == 1800  # 30 min * 60

        # Login attempts should be reset
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        """Wrong password should raise AuthenticationError and increment attempts."""
        admin = _make_admin_orm()
        mock_factory, _ = _mock_session_factory(admin=admin)
        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)
        mock_redis.incr = AsyncMock(return_value=1)

        with (
            patch("app.services.auth.service.get_session_factory", return_value=mock_factory),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
        ):
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                await service.login("admin@cri-rabat.ma", "wrong-password")

        # Failed attempt should be recorded
        mock_redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_inactive_admin(self):
        """Inactive admin should raise AuthenticationError."""
        # Return None to simulate no active admin found
        mock_factory, _ = _mock_session_factory(admin=None)
        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)
        mock_redis.incr = AsyncMock(return_value=1)

        with (
            patch("app.services.auth.service.get_session_factory", return_value=mock_factory),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
        ):
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                await service.login("inactive@cri.ma", "SecureP@ss123!")

    @pytest.mark.asyncio
    async def test_login_rate_limiting(self):
        """Account should be locked after 5 failed attempts."""
        mock_redis = AsyncMock()
        # Simulate lockout active with 1500 seconds remaining
        mock_redis.ttl = AsyncMock(return_value=1500)

        with patch("app.services.auth.service.get_redis", return_value=mock_redis):
            service = AuthService()
            with pytest.raises(AccountLockedError) as exc_info:
                await service.login("admin@cri-rabat.ma", "any-password")

        assert exc_info.value.remaining_seconds == 1500


# --- Refresh token tests ---


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_refresh_token_rotation(self):
        """Valid refresh should invalidate old token and return new pair."""
        admin = _make_admin_orm()
        mock_factory, _ = _mock_session_factory(admin=admin)
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)  # Token is valid

        with (
            patch("app.services.auth.service.get_session_factory", return_value=mock_factory),
            patch("app.services.auth.service.get_settings") as mock_settings,
            patch("app.services.auth.jwt.get_settings") as mock_jwt_settings,
            patch("app.services.auth.jwt.get_redis", return_value=mock_redis),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
        ):
            settings = MagicMock(
                jwt_secret_key="test-secret",
                jwt_algorithm="HS256",
                jwt_access_token_expire_minutes=30,
                jwt_refresh_token_expire_days=7,
            )
            mock_settings.return_value = settings
            mock_jwt_settings.return_value = settings

            # Create a valid refresh token first
            refresh_token, jti = await JWTManager.create_refresh_token(admin.id)

            service = AuthService()
            result = await service.refresh_token(refresh_token)

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

        # Old jti should have been invalidated (deleted)
        mock_redis.delete.assert_any_call(f"auth:refresh_token:{jti}")

    @pytest.mark.asyncio
    async def test_refresh_token_reuse_rejected(self):
        """Already-used refresh token should be rejected."""
        admin = _make_admin_orm()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)  # Token already used

        with (
            patch("app.services.auth.jwt.get_settings") as mock_settings,
            patch("app.services.auth.jwt.get_redis", return_value=mock_redis),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
        ):
            settings = MagicMock(
                jwt_secret_key="test-secret",
                jwt_algorithm="HS256",
                jwt_access_token_expire_minutes=30,
                jwt_refresh_token_expire_days=7,
            )
            mock_settings.return_value = settings

            # Create a token (stores jti in Redis mock)
            refresh_token, _jti = await JWTManager.create_refresh_token(admin.id)

            # Now mock exists to return 0 (token already used)
            mock_redis.exists = AsyncMock(return_value=0)

            service = AuthService()
            with pytest.raises(AuthenticationError, match="already used"):
                await service.refresh_token(refresh_token)
