"""Authentication service — login, refresh, password management.

Implements rate-limited login with Redis-backed lockout,
bcrypt password hashing (cost factor 12), and JWT refresh
token rotation (single-use).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import bcrypt as _bcrypt
import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.exceptions import AccountLockedError, AuthenticationError
from app.core.metrics import LOGIN_ATTEMPTS
from app.core.redis import get_redis
from app.models.admin import Admin
from app.schemas.auth import AdminTokenPayload, AuthTokenResponse
from app.services.auth.jwt import JWTManager

logger = structlog.get_logger()

# Bcrypt cost factor
_BCRYPT_ROUNDS = 12

# Rate limiting constants
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = 900  # 15 minutes in seconds
LOCKOUT_DURATION = 1800  # 30 minutes in seconds

# Redis key patterns (no tenant prefix — auth is global/public schema)
_ATTEMPTS_KEY = "auth:login_attempts:{email}"
_LOCKOUT_KEY = "auth:lockout:{email}"


class AuthService:
    """Authentication service for back-office admins."""

    def __init__(self) -> None:
        self.logger = logger.bind(service="auth")
        self.jwt = JWTManager()

    async def login(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
    ) -> AuthTokenResponse:
        """Authenticate admin by email/password.

        Args:
            email: Admin email address.
            password: Plain-text password.
            ip_address: Client IP (enables advanced session tracking).

        Returns:
            AuthTokenResponse with access + refresh tokens.

        Raises:
            AccountLockedError: Too many failed attempts.
            AuthenticationError: Invalid credentials or inactive account.
        """
        log = self.logger.bind(email=email)

        # 1. Check lockout
        await self._check_rate_limit(email)

        # 2. Fetch admin from DB
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Admin).where(
                    Admin.email == email,
                    Admin.is_active.is_(True),
                )
            )
            admin = result.scalar_one_or_none()

        if not admin:
            await self._record_failed_attempt(email)
            LOGIN_ATTEMPTS.labels(tenant="", status="failed").inc()
            log.warning("login_failed", reason="admin_not_found_or_inactive")
            raise AuthenticationError("Invalid credentials")

        # 3. Verify password
        if not self.verify_password(password, admin.password_hash):
            await self._record_failed_attempt(email)
            LOGIN_ATTEMPTS.labels(tenant="", status="failed").inc()
            log.warning("login_failed", reason="wrong_password", admin_id=str(admin.id))
            raise AuthenticationError("Invalid credentials")

        # 4. Success — generate tokens
        access_token, access_jti = JWTManager.create_access_token(
            admin_id=admin.id,
            role=admin.role.value,
            tenant_id=admin.tenant_id,
        )
        refresh_token, _jti = await JWTManager.create_refresh_token(admin_id=admin.id)

        # 4b. Register advanced session (IP tracking, single session)
        if ip_address:
            from app.services.auth.session_manager import get_session_manager

            session_mgr = get_session_manager()
            session_result = await session_mgr.register_session(
                admin_id=str(admin.id),
                jti=access_jti,
                ip_address=ip_address,
            )
            if session_result.get("ip_alert"):
                log.warning("ip_change_alert_on_login", admin_id=str(admin.id))

        # 5. Reset attempts and update last_login
        await self._reset_attempts(email)

        async with factory() as session:
            result = await session.execute(select(Admin).where(Admin.id == admin.id))
            db_admin = result.scalar_one()
            db_admin.last_login = datetime.now(UTC)
            await session.commit()

        settings = get_settings()
        LOGIN_ATTEMPTS.labels(tenant="", status="success").inc()
        log.info("login_success", admin_id=str(admin.id), role=admin.role.value)

        return AuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    async def refresh_token(self, refresh_token_str: str) -> AuthTokenResponse:
        """Rotate a refresh token (single-use).

        Args:
            refresh_token_str: The current refresh token JWT.

        Returns:
            New AuthTokenResponse with fresh access + refresh tokens.

        Raises:
            AuthenticationError: If token is invalid, expired, or already used.
        """
        # 1. Verify JWT
        payload = JWTManager.verify_token(refresh_token_str)

        # 2. Must be a refresh token
        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type")

        jti = payload.get("jti")
        if not jti:
            raise AuthenticationError("Invalid token: missing jti")

        # 3. Check single-use (jti must still exist in Redis)
        if not await JWTManager.is_refresh_token_valid(jti):
            self.logger.warning(
                "refresh_token_reuse_detected",
                admin_id=payload.get("sub"),
                jti=jti,
            )
            raise AuthenticationError("Refresh token already used")

        # 4. Invalidate old jti (rotation)
        await JWTManager.invalidate_refresh_token(jti)

        # 5. Fetch current admin state (role/tenant may have changed)
        admin_id = uuid.UUID(payload["sub"])
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Admin).where(Admin.id == admin_id, Admin.is_active.is_(True))
            )
            admin = result.scalar_one_or_none()

        if not admin:
            raise AuthenticationError("Admin account no longer active")

        # 6. Issue new token pair
        access_token, _access_jti = JWTManager.create_access_token(
            admin_id=admin.id,
            role=admin.role.value,
            tenant_id=admin.tenant_id,
        )
        new_refresh_token, _jti = await JWTManager.create_refresh_token(admin_id=admin.id)

        settings = get_settings()
        self.logger.info("token_refreshed", admin_id=str(admin.id))

        return AuthTokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    async def verify_access_token(
        self,
        token: str,
        ip_address: str | None = None,
    ) -> AdminTokenPayload:
        """Verify an access token and return its payload.

        When ``ip_address`` is provided, also validates the session
        against Redis (JTI active, IP unchanged).

        Args:
            token: Encoded JWT access token.
            ip_address: Client IP for session validation (optional).

        Returns:
            Validated AdminTokenPayload.

        Raises:
            AuthenticationError: If token is invalid, not an access token,
                or session has been invalidated.
        """
        payload = JWTManager.verify_token(token)
        if payload.get("type") != "access":
            raise AuthenticationError("Invalid token type")

        payload_obj = AdminTokenPayload(**payload)

        # Advanced session validation (Phase 2)
        if ip_address:
            from app.services.auth.session_manager import get_session_manager

            session_mgr = get_session_manager()
            is_valid = await session_mgr.validate_session(
                admin_id=payload_obj.sub,
                jti=payload_obj.jti,
                ip_address=ip_address,
            )
            if not is_valid:
                raise AuthenticationError("Session invalidated")

        return payload_obj

    async def logout(
        self,
        refresh_token_jti: str,
        admin_id: str | None = None,
    ) -> None:
        """Invalidate refresh token and active session on logout.

        Args:
            refresh_token_jti: The jti of the refresh token to invalidate.
            admin_id: UUID string of the admin (invalidates access session too).
        """
        await JWTManager.invalidate_refresh_token(refresh_token_jti)

        # Also invalidate the access token session (Phase 2)
        if admin_id:
            from app.services.auth.session_manager import get_session_manager

            session_mgr = get_session_manager()
            await session_mgr.invalidate_session(admin_id)

        self.logger.info("logout", jti=refresh_token_jti, admin_id=admin_id)

    @staticmethod
    def _prehash(password: str) -> bytes:
        """SHA-256 pre-hash to safely handle passwords > 72 bytes for bcrypt."""
        return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password with bcrypt (cost factor 12).

        Args:
            password: Plain-text password.

        Returns:
            Bcrypt hash string.
        """
        return _bcrypt.hashpw(
            AuthService._prehash(password),
            _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
        ).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """Verify a plain-text password against a bcrypt hash.

        Args:
            plain: Plain-text password.
            hashed: Bcrypt hash to verify against.

        Returns:
            True if password matches.
        """
        return _bcrypt.checkpw(
            AuthService._prehash(plain),
            hashed.encode("utf-8"),
        )

    # ── Rate limiting helpers ──

    async def _check_rate_limit(self, email: str) -> None:
        """Check if login is rate-limited for this email.

        Raises:
            AccountLockedError: If account is currently locked out.
        """
        redis = get_redis()
        lockout_key = _LOCKOUT_KEY.format(email=email)
        lockout_ttl = await redis.ttl(lockout_key)

        if lockout_ttl > 0:
            LOGIN_ATTEMPTS.labels(tenant="", status="locked").inc()
            self.logger.warning("login_locked_out", email=email, remaining=lockout_ttl)
            raise AccountLockedError(remaining_seconds=lockout_ttl)

    async def _record_failed_attempt(self, email: str) -> None:
        """Increment failed login counter. Trigger lockout if threshold reached."""
        redis = get_redis()
        attempts_key = _ATTEMPTS_KEY.format(email=email)

        # Increment counter
        count = await redis.incr(attempts_key)

        # Set TTL on first attempt
        if count == 1:
            await redis.expire(attempts_key, LOGIN_ATTEMPT_WINDOW)

        # Trigger lockout if threshold reached
        if count >= MAX_LOGIN_ATTEMPTS:
            lockout_key = _LOCKOUT_KEY.format(email=email)
            await redis.setex(lockout_key, LOCKOUT_DURATION, "1")
            await redis.delete(attempts_key)
            self.logger.warning(
                "account_locked",
                email=email,
                attempts=count,
                lockout_seconds=LOCKOUT_DURATION,
            )

    async def _reset_attempts(self, email: str) -> None:
        """Reset login attempt counter on successful login."""
        redis = get_redis()
        attempts_key = _ATTEMPTS_KEY.format(email=email)
        await redis.delete(attempts_key)
