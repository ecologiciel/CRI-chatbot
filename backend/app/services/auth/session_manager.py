"""Advanced session management — IP tracking, single session, alerts.

Complements Phase 1 JWT auth with Redis-backed session state:
- One active session per admin (new login invalidates previous)
- IP address tracking per session (change → immediate revocation)
- Suspicious login alerts (2 different IPs within 5 minutes)

All session data is volatile (Redis TTL). No DB writes.

Redis key patterns (no tenant prefix — auth is global/public):
    auth:session:{admin_id}:active     → JTI of active access token
    auth:session:{admin_id}:ip         → IP of active session
    auth:session:{admin_id}:last_login → UTC timestamp string
    auth:alert:{admin_id}              → Suspicious IP alert flag
    auth:revoked:{jti}                 → Revoked token marker
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.core.metrics import ACTIVE_SESSIONS

logger = structlog.get_logger()

# Redis key templates
_SESSION_PREFIX = "auth:session"
_ALERT_PREFIX = "auth:alert"
_REVOKED_PREFIX = "auth:revoked"

# TTLs (seconds)
_ACCESS_TOKEN_TTL = 1800  # 30 min — matches JWT access token lifetime
_LAST_LOGIN_TTL = 86400  # 24 h
_ALERT_WINDOW_SECONDS = 300  # 5 min — suspicious IP detection window


class SessionManager:
    """Manage advanced admin sessions with integrity controls.

    Attributes:
        _redis: Async Redis client (injected for testability).
    """

    def __init__(self, redis_client) -> None:  # noqa: ANN001
        self._redis = redis_client

    # ── Public API ──────────────────────────────────────────────

    async def register_session(
        self,
        admin_id: str,
        jti: str,
        ip_address: str,
    ) -> dict:
        """Register a new session after successful login.

        1. Invalidate any previous active session (single-session rule).
        2. Detect suspicious IP change within the alert window.
        3. Store the new session keys (jti, ip, last_login).

        Args:
            admin_id: UUID string of the admin.
            jti: JWT ID of the new access token.
            ip_address: Client IP address.

        Returns:
            Dict with ``previous_session_invalidated`` and ``ip_alert`` flags.
        """
        result = {"previous_session_invalidated": False, "ip_alert": False}

        key_active = f"{_SESSION_PREFIX}:{admin_id}:active"
        key_ip = f"{_SESSION_PREFIX}:{admin_id}:ip"
        key_last = f"{_SESSION_PREFIX}:{admin_id}:last_login"
        key_alert = f"{_ALERT_PREFIX}:{admin_id}"

        # 1. Single session: revoke previous if exists
        existing_jti = await self._redis.get(key_active)
        if existing_jti and existing_jti != jti:
            await self._redis.setex(
                f"{_REVOKED_PREFIX}:{existing_jti}",
                _ACCESS_TOKEN_TTL,
                "revoked",
            )
            result["previous_session_invalidated"] = True
            logger.info(
                "session_invalidated",
                admin_id=admin_id,
                old_jti=existing_jti,
                reason="new_login",
            )

        # 2. Suspicious IP detection
        last_ip = await self._redis.get(key_ip)
        last_login_ts = await self._redis.get(key_last)
        if last_ip and last_ip != ip_address and last_login_ts:
            elapsed = datetime.now(UTC).timestamp() - float(last_login_ts)
            if elapsed < _ALERT_WINDOW_SECONDS:
                result["ip_alert"] = True
                await self._redis.setex(
                    key_alert,
                    _ALERT_WINDOW_SECONDS,
                    ip_address,
                )
                logger.warning(
                    "suspicious_login_detected",
                    admin_id=admin_id,
                    previous_ip=last_ip,
                    new_ip=ip_address,
                    elapsed_seconds=round(elapsed, 1),
                )

        # 3. Store new session (pipeline for atomicity)
        now_ts = str(datetime.now(UTC).timestamp())
        pipe = self._redis.pipeline()
        pipe.setex(key_active, _ACCESS_TOKEN_TTL, jti)
        pipe.setex(key_ip, _ACCESS_TOKEN_TTL, ip_address)
        pipe.setex(key_last, _LAST_LOGIN_TTL, now_ts)
        await pipe.execute()

        # Prometheus: track active sessions (approximate — resets on restart)
        if not result["previous_session_invalidated"]:
            ACTIVE_SESSIONS.labels(tenant="").inc()

        return result

    async def validate_session(
        self,
        admin_id: str,
        jti: str,
        ip_address: str,
    ) -> bool:
        """Validate that a session is still active and consistent.

        Called on every authenticated request via the RBAC dependency.

        Checks:
            1. Token not revoked.
            2. JTI matches the active session.
            3. IP address has not changed.

        Args:
            admin_id: UUID string of the admin.
            jti: JWT ID from the access token.
            ip_address: Current request client IP.

        Returns:
            True if the session is valid.

        Raises:
            Nothing — returns False on failure (caller decides error).
        """
        # 1. Check revocation
        if await self.is_token_revoked(jti):
            logger.info("session_rejected_revoked", admin_id=admin_id, jti=jti)
            return False

        key_active = f"{_SESSION_PREFIX}:{admin_id}:active"
        key_ip = f"{_SESSION_PREFIX}:{admin_id}:ip"

        # 2. Check JTI matches active session
        active_jti = await self._redis.get(key_active)
        if not active_jti or active_jti != jti:
            logger.info(
                "session_rejected_superseded",
                admin_id=admin_id,
                expected_jti=active_jti,
                actual_jti=jti,
            )
            return False

        # 3. Check IP consistency
        session_ip = await self._redis.get(key_ip)
        if session_ip and session_ip != ip_address:
            logger.warning(
                "session_ip_changed",
                admin_id=admin_id,
                expected_ip=session_ip,
                actual_ip=ip_address,
            )
            # Revoke and invalidate
            await self.invalidate_session(admin_id)
            return False

        return True

    async def invalidate_session(self, admin_id: str) -> None:
        """Invalidate an admin's active session (logout or anomaly).

        Revokes the active JTI and removes session keys.

        Args:
            admin_id: UUID string of the admin.
        """
        key_active = f"{_SESSION_PREFIX}:{admin_id}:active"
        key_ip = f"{_SESSION_PREFIX}:{admin_id}:ip"

        active_jti = await self._redis.get(key_active)
        if active_jti:
            await self._redis.setex(
                f"{_REVOKED_PREFIX}:{active_jti}",
                _ACCESS_TOKEN_TTL,
                "revoked",
            )

        await self._redis.delete(key_active, key_ip)
        ACTIVE_SESSIONS.labels(tenant="").dec()
        logger.info("session_invalidated", admin_id=admin_id, reason="explicit")

    async def is_token_revoked(self, jti: str) -> bool:
        """Check if a token JTI has been revoked.

        Args:
            jti: JWT ID to check.

        Returns:
            True if the token is on the revocation list.
        """
        return await self._redis.exists(f"{_REVOKED_PREFIX}:{jti}") > 0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get or create the SessionManager singleton."""
    global _session_manager  # noqa: PLW0603
    if _session_manager is None:
        from app.core.redis import get_redis

        _session_manager = SessionManager(get_redis())
    return _session_manager
