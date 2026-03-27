"""Unit tests for AuthService — password hashing, login, refresh, verify, logout."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AccountLockedError, AuthenticationError
from app.models.enums import AdminRole
from app.services.auth.service import AuthService
from tests.unit.conftest import TEST_ADMIN_ID, TEST_TENANT_ID, make_admin_orm, make_session_factory

_SESSION_FACTORY_PATCH = "app.services.auth.service.get_session_factory"
_REDIS_PATCH = "app.services.auth.service.get_redis"
_SETTINGS_PATCH = "app.services.auth.jwt.get_settings"
_JWT_REDIS_PATCH = "app.services.auth.jwt.get_redis"


def _make_jwt_settings():
    """Mock settings for JWTManager."""
    s = MagicMock()
    s.jwt_secret_key = "test-secret-key-for-jwt"
    s.jwt_algorithm = "HS256"
    s.jwt_access_token_expire_minutes = 30
    s.jwt_refresh_token_expire_days = 7
    return s


class TestPasswordHashing:
    """AuthService.hash_password / verify_password."""

    def test_hash_password_bcrypt_format(self):
        """hash_password produces $2b$12$ prefix (bcrypt cost 12)."""
        hashed = AuthService.hash_password("TestP@ss123!")
        assert hashed.startswith("$2b$")
        assert AuthService.verify_password("TestP@ss123!", hashed) is True

    def test_verify_password_wrong_returns_false(self):
        """Wrong password returns False."""
        hashed = AuthService.hash_password("CorrectP@ss1!")
        assert AuthService.verify_password("WrongP@ss2!", hashed) is False


class TestLogin:
    """AuthService.login() — success and failure paths."""

    @pytest.mark.asyncio
    async def test_login_success_returns_tokens(self):
        """Valid credentials produce access_token + refresh_token."""
        admin = make_admin_orm()
        factory, session = make_session_factory(admin=admin)

        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)  # No lockout
        mock_redis.delete = AsyncMock()

        jwt_redis = AsyncMock()
        jwt_redis.setex = AsyncMock()

        with (
            patch(_SESSION_FACTORY_PATCH, return_value=factory),
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()),
            patch(_JWT_REDIS_PATCH, return_value=jwt_redis),
        ):
            service = AuthService()
            result = await service.login("admin@cri-rabat.ma", "SecureP@ss123!")

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises(self):
        """Wrong password raises AuthenticationError."""
        admin = make_admin_orm()
        factory, _ = make_session_factory(admin=admin)

        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with (
            patch(_SESSION_FACTORY_PATCH, return_value=factory),
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()),
        ):
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                await service.login("admin@cri-rabat.ma", "WrongP@ss!")

    @pytest.mark.asyncio
    async def test_login_locked_raises(self):
        """TTL > 0 on lockout key triggers AccountLockedError."""
        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=1500)  # Locked for 1500s

        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()),
        ):
            service = AuthService()
            with pytest.raises(AccountLockedError):
                await service.login("admin@cri-rabat.ma", "AnyP@ss1!")


class TestVerifyAccessToken:
    """AuthService.verify_access_token() — type checking."""

    @pytest.mark.asyncio
    async def test_verify_access_token_with_refresh_raises(self):
        """Passing a refresh token to verify_access_token raises."""
        from app.services.auth.jwt import JWTManager

        jwt_redis = AsyncMock()
        jwt_redis.setex = AsyncMock()

        with (
            patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()),
            patch(_JWT_REDIS_PATCH, return_value=jwt_redis),
        ):
            # Create a refresh token
            refresh_token, jti = await JWTManager.create_refresh_token(
                admin_id=TEST_ADMIN_ID,
            )

        with patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()):
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.verify_access_token(refresh_token)


class TestLogout:
    """AuthService.logout() invalidates the refresh token JTI."""

    @pytest.mark.asyncio
    async def test_logout_invalidates_jti(self):
        """logout() calls JWTManager.invalidate_refresh_token."""
        jwt_redis = AsyncMock()
        jwt_redis.delete = AsyncMock()

        with (
            patch(_SETTINGS_PATCH, return_value=_make_jwt_settings()),
            patch(_JWT_REDIS_PATCH, return_value=jwt_redis),
        ):
            service = AuthService()
            await service.logout("test-jti-123")

        jwt_redis.delete.assert_called_once()
