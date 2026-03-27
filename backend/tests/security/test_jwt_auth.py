"""JWT authentication security tests.

Tests token lifecycle, tampering, type confusion, and invalidation.
Complements test_auth_service.py with edge-case security scenarios.
"""

import base64
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthenticationError
from app.models.enums import AdminRole
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService


def _mock_settings(**overrides):
    """Create mock settings with JWT defaults."""
    defaults = {
        "jwt_secret_key": "test-jwt-secret-key",
        "jwt_algorithm": "HS256",
        "jwt_access_token_expire_minutes": 30,
        "jwt_refresh_token_expire_days": 7,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestJWTTokenSecurity:
    """JWT token creation, verification, and security edge cases."""

    def test_access_token_roundtrip(self):
        """Create access token → verify → payload fields match."""
        admin_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()):
            token = JWTManager.create_access_token(
                admin_id=admin_id,
                role=AdminRole.admin_tenant.value,
                tenant_id=tenant_id,
            )
            payload = JWTManager.verify_token(token)

        assert payload["sub"] == str(admin_id)
        assert payload["role"] == "admin_tenant"
        assert payload["tenant_id"] == str(tenant_id)
        assert payload["type"] == "access"

    def test_wrong_secret_rejected(self):
        """Token signed with key A, verified with key B → AuthenticationError."""
        admin_id = uuid.uuid4()

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings(jwt_secret_key="secret-A")):
            token = JWTManager.create_access_token(
                admin_id=admin_id,
                role=AdminRole.admin_tenant.value,
                tenant_id=None,
            )

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings(jwt_secret_key="secret-B")):
            with pytest.raises(AuthenticationError, match="Invalid token"):
                JWTManager.verify_token(token)

    def test_expired_token_rejected(self):
        """Expired token raises AuthenticationError."""
        admin_id = uuid.uuid4()

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings(jwt_access_token_expire_minutes=-1)):
            token = JWTManager.create_access_token(
                admin_id=admin_id,
                role=AdminRole.admin_tenant.value,
                tenant_id=None,
            )

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()):
            with pytest.raises(AuthenticationError, match="Token has expired"):
                JWTManager.verify_token(token)

    @pytest.mark.asyncio
    async def test_refresh_used_as_access_rejected(self):
        """Refresh token passed to verify_access_token raises type error."""
        admin_id = uuid.uuid4()
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with (
            patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()),
            patch("app.services.auth.jwt.get_redis", return_value=mock_redis),
            patch("app.services.auth.service.get_settings", return_value=_mock_settings()),
        ):
            refresh_token, _jti = await JWTManager.create_refresh_token(admin_id=admin_id)
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.verify_access_token(refresh_token)

    @pytest.mark.asyncio
    async def test_access_used_as_refresh_rejected(self):
        """Access token passed to refresh_token raises type error."""
        admin_id = uuid.uuid4()

        with (
            patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()),
            patch("app.services.auth.service.get_settings", return_value=_mock_settings()),
            patch("app.services.auth.service.get_session_factory") as mock_factory,
            patch("app.services.auth.service.get_redis", return_value=AsyncMock()),
        ):
            access_token = JWTManager.create_access_token(
                admin_id=admin_id,
                role=AdminRole.admin_tenant.value,
                tenant_id=None,
            )
            service = AuthService()
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await service.refresh_token(access_token)

    def test_tampered_payload_rejected(self):
        """Modifying the payload without re-signing invalidates the token."""
        admin_id = uuid.uuid4()

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()):
            token = JWTManager.create_access_token(
                admin_id=admin_id,
                role=AdminRole.admin_tenant.value,
                tenant_id=None,
            )

        # Tamper with the payload (change role to super_admin)
        parts = token.split(".")
        # Decode payload (add padding)
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload_data = json.loads(base64.urlsafe_b64decode(payload_b64))
        payload_data["role"] = "super_admin"
        # Re-encode without re-signing
        tampered_payload = base64.urlsafe_b64encode(
            json.dumps(payload_data).encode()
        ).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        with patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()):
            with pytest.raises(AuthenticationError, match="Invalid token"):
                JWTManager.verify_token(tampered_token)

    @pytest.mark.asyncio
    async def test_refresh_single_use(self):
        """Using a refresh token twice fails on the second attempt."""
        admin_id = uuid.uuid4()
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        # First check: exists (valid), second check: doesn't exist (used)
        mock_redis.exists = AsyncMock(side_effect=[1, 0])
        mock_redis.delete = AsyncMock()

        mock_admin = MagicMock()
        mock_admin.id = admin_id
        mock_admin.role = MagicMock(value=AdminRole.admin_tenant.value)
        mock_admin.tenant_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_admin
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(return_value=mock_session)

        with (
            patch("app.services.auth.jwt.get_settings", return_value=_mock_settings()),
            patch("app.services.auth.jwt.get_redis", return_value=mock_redis),
            patch("app.services.auth.service.get_settings", return_value=_mock_settings()),
            patch("app.services.auth.service.get_session_factory", return_value=mock_factory),
            patch("app.services.auth.service.get_redis", return_value=mock_redis),
        ):
            refresh_token, _jti = await JWTManager.create_refresh_token(admin_id=admin_id)
            service = AuthService()

            # First refresh: should succeed
            await service.refresh_token(refresh_token)

            # Second refresh with same token: should fail
            with pytest.raises(AuthenticationError, match="Refresh token already used"):
                await service.refresh_token(refresh_token)

    @pytest.mark.asyncio
    async def test_deactivated_admin_rejected(self):
        """Valid token for deactivated admin is rejected by get_current_admin."""
        from app.core.rbac import get_current_admin
        from app.schemas.auth import AdminTokenPayload
        from fastapi.security import HTTPAuthorizationCredentials

        admin_id = uuid.uuid4()
        valid_payload = AdminTokenPayload(
            sub=str(admin_id),
            role=AdminRole.admin_tenant.value,
            tenant_id=str(uuid.uuid4()),
            exp=9999999999,
            iat=1700000000,
            jti=str(uuid.uuid4()),
            type="access",
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        # Admin not found (deactivated) → scalar_one_or_none returns None
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(return_value=mock_session)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake-token")

        with (
            patch("app.core.rbac.AuthService") as MockAuthService,
            patch("app.core.rbac.get_session_factory", return_value=mock_factory),
        ):
            mock_auth = AsyncMock()
            mock_auth.verify_access_token = AsyncMock(return_value=valid_payload)
            MockAuthService.return_value = mock_auth

            with pytest.raises(AuthenticationError, match="no longer active"):
                await get_current_admin(credentials=credentials)
