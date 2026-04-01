"""DossierOTPService -- OTP authentication for dossier tracking via WhatsApp.

Redis-only stateless service (no PostgreSQL dependency).
All keys are tenant-scoped via {tenant.slug} prefix.

Security measures (par.3.5.3):
- OTP generated via secrets.randbelow (crypto-secure, 6 digits)
- SHA-256 hash stored in Redis -- plaintext NEVER persisted
- Anti-replay: OTP key deleted immediately on successful verification
- Anti-bruteforce: max 3 attempts per phone per 15 minutes
- Audit trail: every generate/verify/fail logged via AuditService
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app.core.exceptions import AuthenticationError, RateLimitExceededError
from app.core.redis import get_redis
from app.schemas.audit import AuditLogCreate
from app.services.audit import get_audit_service

if TYPE_CHECKING:
    from app.core.tenant import TenantContext

logger = structlog.get_logger()

# -- Constants --------------------------------------------------------------

OTP_TTL = 300  # 5 minutes
MAX_OTP_ATTEMPTS = 3
ATTEMPT_WINDOW = 900  # 15 minutes
SESSION_TTL = 1800  # 30 minutes (sliding window)
SESSION_TOKEN_BYTES = 32  # token_hex(32) = 64 hex chars


class DossierOTPService:
    """OTP authentication for dossier tracking via WhatsApp.

    Redis-only stateless service. No PostgreSQL dependency.
    All keys are tenant-scoped via {tenant.slug} prefix.
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="dossier_otp")

    # -- Private helpers ----------------------------------------------------

    @staticmethod
    def _redis_key(tenant: TenantContext, key_type: str, identifier: str) -> str:
        """Build a tenant-scoped Redis key."""
        return f"{tenant.slug}:{key_type}:{identifier}"

    async def _audit(
        self,
        tenant: TenantContext,
        action: str,
        phone: str,
        *,
        details: dict | None = None,
    ) -> None:
        """Fire-and-forget audit log via AuditService."""
        try:
            audit = get_audit_service()
            await audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_id=None,
                    user_type="whatsapp_user",
                    action=action,
                    resource_type="dossier_otp",
                    resource_id=phone[-4:],
                    details=details or {},
                ),
            )
        except Exception:
            self._logger.warning(
                "audit_log_failed",
                action=action,
                tenant=tenant.slug,
            )

    # -- Public API ---------------------------------------------------------

    async def is_rate_limited(self, tenant: TenantContext, phone: str) -> bool:
        """Check if a phone number has exceeded OTP attempt limit.

        Args:
            tenant: Current tenant context.
            phone: Phone number in E.164 format.

        Returns:
            True if rate limit reached (>= 3 attempts in 15 min).
        """
        redis = get_redis()
        key = self._redis_key(tenant, "dossier_otp_attempts", phone)
        attempts = await redis.get(key)
        if attempts is None:
            return False
        return int(attempts) >= MAX_OTP_ATTEMPTS

    async def generate_otp(self, phone: str, tenant: TenantContext) -> str:
        """Generate a 6-digit OTP for dossier tracking authentication.

        Args:
            phone: Phone number in E.164 format.
            tenant: Current tenant context.

        Returns:
            The plaintext OTP (for WhatsApp delivery by caller).

        Raises:
            RateLimitExceededError: If phone has exceeded 3 attempts in 15 min.
        """
        if await self.is_rate_limited(tenant, phone):
            self._logger.warning(
                "otp_rate_limited",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
            )
            raise RateLimitExceededError(
                "OTP rate limit exceeded. Try again later.",
                details={"phone_last4": phone[-4:]},
            )

        redis = get_redis()

        # Generate crypto-secure 6-digit OTP
        otp = str(secrets.randbelow(900000) + 100000)
        otp_hash = hashlib.sha256(otp.encode()).hexdigest()

        # Store hash in Redis (NEVER plaintext)
        otp_key = self._redis_key(tenant, "dossier_otp", phone)
        await redis.set(otp_key, otp_hash, ex=OTP_TTL)

        # Increment attempt counter
        attempts_key = self._redis_key(tenant, "dossier_otp_attempts", phone)
        count = await redis.incr(attempts_key)
        if count == 1:
            await redis.expire(attempts_key, ATTEMPT_WINDOW)

        self._logger.info(
            "otp_generated",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )

        await self._audit(tenant, "otp_generate", phone)

        return otp

    async def verify_otp(
        self, phone: str, otp_code: str, tenant: TenantContext,
    ) -> bool:
        """Verify an OTP code against the stored hash.

        On success, the OTP key is deleted immediately (anti-replay).

        Args:
            phone: Phone number in E.164 format.
            otp_code: The 6-digit OTP code to verify.
            tenant: Current tenant context.

        Returns:
            True if OTP is valid, False otherwise.
        """
        redis = get_redis()
        otp_key = self._redis_key(tenant, "dossier_otp", phone)
        stored_hash = await redis.get(otp_key)

        if stored_hash is None:
            self._logger.info(
                "otp_verify_fail",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                reason="expired_or_missing",
            )
            await self._audit(
                tenant, "otp_verify_fail", phone,
                details={"reason": "expired_or_missing"},
            )
            return False

        # Decode bytes from Redis
        if isinstance(stored_hash, bytes):
            stored_hash = stored_hash.decode()

        # Compare hashes
        computed_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        if computed_hash != stored_hash:
            self._logger.info(
                "otp_verify_fail",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                reason="invalid_code",
            )
            await self._audit(
                tenant, "otp_verify_fail", phone,
                details={"reason": "invalid_code"},
            )
            return False

        # Anti-replay: delete OTP key immediately
        await redis.delete(otp_key)

        self._logger.info(
            "otp_verify_success",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )
        await self._audit(tenant, "otp_verify_success", phone)

        return True

    async def create_dossier_session(
        self, phone: str, tenant: TenantContext,
    ) -> str:
        """Create an authenticated dossier consultation session.

        Args:
            phone: Verified phone number in E.164 format.
            tenant: Current tenant context.

        Returns:
            Session token (64-char hex string).
        """
        redis = get_redis()
        token = secrets.token_hex(SESSION_TOKEN_BYTES)

        session_key = self._redis_key(tenant, "dossier_session", phone)
        session_data = json.dumps({
            "token": token,
            "phone": phone,
            "created_at": datetime.now(UTC).isoformat(),
        })
        await redis.set(session_key, session_data, ex=SESSION_TTL)

        self._logger.info(
            "dossier_session_created",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )
        await self._audit(tenant, "dossier_session_create", phone)

        return token

    async def validate_dossier_session(
        self,
        phone: str,
        session_token: str,
        tenant: TenantContext,
    ) -> bool:
        """Validate a dossier consultation session token.

        On success, the session TTL is renewed (sliding window).

        Args:
            phone: Phone number in E.164 format.
            session_token: The session token to validate.
            tenant: Current tenant context.

        Returns:
            True if session is valid, False otherwise.
        """
        redis = get_redis()
        session_key = self._redis_key(tenant, "dossier_session", phone)
        raw = await redis.get(session_key)

        if raw is None:
            return False

        if isinstance(raw, bytes):
            raw = raw.decode()

        session_data = json.loads(raw)
        if session_data.get("token") != session_token:
            return False

        # Sliding window: renew TTL on each successful validation
        await redis.expire(session_key, SESSION_TTL)
        return True

    async def invalidate_session(
        self, phone: str, tenant: TenantContext,
    ) -> None:
        """Invalidate (delete) a dossier consultation session.

        Args:
            phone: Phone number in E.164 format.
            tenant: Current tenant context.
        """
        redis = get_redis()
        session_key = self._redis_key(tenant, "dossier_session", phone)
        await redis.delete(session_key)

        self._logger.info(
            "dossier_session_invalidated",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )
        await self._audit(tenant, "dossier_session_invalidate", phone)


# -- Singleton --------------------------------------------------------------

_dossier_otp_service: DossierOTPService | None = None


def get_dossier_otp_service() -> DossierOTPService:
    """Get or create the DossierOTPService singleton."""
    global _dossier_otp_service
    if _dossier_otp_service is None:
        _dossier_otp_service = DossierOTPService()
    return _dossier_otp_service
