"""JWT token creation and verification.

Access tokens carry admin identity and role for stateless auth.
Refresh tokens are single-use: their jti is stored in Redis and
deleted on use (rotation).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.redis import get_redis

logger = structlog.get_logger()

_REFRESH_TOKEN_REDIS_PREFIX = "auth:refresh_token"


class JWTManager:
    """Handles JWT token creation and verification."""

    @staticmethod
    def create_access_token(
        admin_id: uuid.UUID,
        role: str,
        tenant_id: uuid.UUID | None,
    ) -> tuple[str, str]:
        """Create a JWT access token.

        Args:
            admin_id: Admin's UUID.
            role: Admin's role (super_admin, admin_tenant, etc.).
            tenant_id: Tenant UUID (None for super_admin).

        Returns:
            Tuple of (encoded JWT string, jti).
        """
        settings = get_settings()
        now = datetime.now(timezone.utc)
        jti = str(uuid.uuid4())
        payload = {
            "sub": str(admin_id),
            "role": role,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.jwt_access_token_expire_minutes)).timestamp()),
            "jti": jti,
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        return token, jti

    @staticmethod
    async def create_refresh_token(admin_id: uuid.UUID) -> tuple[str, str]:
        """Create a refresh token and store its jti in Redis.

        Args:
            admin_id: Admin's UUID.

        Returns:
            Tuple of (encoded JWT string, jti).
        """
        settings = get_settings()
        now = datetime.now(timezone.utc)
        jti = str(uuid.uuid4())
        ttl_seconds = settings.jwt_refresh_token_expire_days * 86400

        payload = {
            "sub": str(admin_id),
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=settings.jwt_refresh_token_expire_days)).timestamp()),
            "jti": jti,
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        # Store jti in Redis for single-use validation
        redis = get_redis()
        await redis.setex(
            f"{_REFRESH_TOKEN_REDIS_PREFIX}:{jti}",
            ttl_seconds,
            "valid",
        )

        logger.debug("refresh_token_created", admin_id=str(admin_id), jti=jti)
        return token, jti

    @staticmethod
    def verify_token(token: str) -> dict:
        """Verify and decode a JWT token.

        Args:
            token: Encoded JWT string.

        Returns:
            Decoded payload dict.

        Raises:
            AuthenticationError: If token is invalid or expired.
        """
        settings = get_settings()
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            return payload
        except ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except JWTError:
            raise AuthenticationError("Invalid token")

    @staticmethod
    async def invalidate_refresh_token(jti: str) -> None:
        """Mark refresh token as used by removing its jti from Redis.

        Args:
            jti: The token's unique identifier.
        """
        redis = get_redis()
        await redis.delete(f"{_REFRESH_TOKEN_REDIS_PREFIX}:{jti}")
        logger.debug("refresh_token_invalidated", jti=jti)

    @staticmethod
    async def is_refresh_token_valid(jti: str) -> bool:
        """Check if a refresh token's jti is still valid (not yet used).

        Args:
            jti: The token's unique identifier.

        Returns:
            True if the jti exists in Redis (token not yet used).
        """
        redis = get_redis()
        return await redis.exists(f"{_REFRESH_TOKEN_REDIS_PREFIX}:{jti}") == 1
