"""Tests for SessionManager — advanced session management (SECURITE.3).

Tests cover: single-session enforcement, IP tracking, suspicious login
alerts, session validation, and token revocation.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.auth.session_manager import SessionManager


# --- Helpers ---


def _make_redis_mock(**overrides):
    """Create a mock Redis client with sane defaults."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    # Pipeline support
    pipe = AsyncMock()
    pipe.setex = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[True, True, True])
    redis.pipeline = MagicMock(return_value=pipe)

    for key, value in overrides.items():
        setattr(redis, key, value)
    return redis


# --- Import ---


class TestImport:
    def test_session_manager_import(self):
        """SessionManager class should be importable."""
        assert SessionManager is not None

    def test_get_session_manager_import(self):
        """Singleton factory should be importable."""
        from app.services.auth.session_manager import get_session_manager

        assert get_session_manager is not None


# --- register_session ---


class TestRegisterSession:
    @pytest.mark.asyncio
    async def test_register_new_session(self):
        """First login — no existing session, no alert."""
        redis = _make_redis_mock()
        sm = SessionManager(redis)

        result = await sm.register_session("admin-123", "jti-abc", "1.2.3.4")

        assert result["previous_session_invalidated"] is False
        assert result["ip_alert"] is False

        # Pipeline should store active jti, ip, last_login
        pipe = redis.pipeline.return_value
        assert pipe.setex.call_count == 3

    @pytest.mark.asyncio
    async def test_register_session_invalidates_previous(self):
        """New login when another session is active — old JTI revoked."""
        redis = _make_redis_mock()
        # Simulate existing active session with a different JTI
        redis.get = AsyncMock(side_effect=["old-jti", None, None])

        sm = SessionManager(redis)
        result = await sm.register_session("admin-123", "new-jti", "1.2.3.4")

        assert result["previous_session_invalidated"] is True
        # Old JTI should be in the revoked set
        redis.setex.assert_any_call("auth:revoked:old-jti", 1800, "revoked")

    @pytest.mark.asyncio
    async def test_register_session_same_jti_no_revoke(self):
        """Re-login with same JTI (e.g., retry) — no revocation."""
        redis = _make_redis_mock()
        redis.get = AsyncMock(side_effect=["same-jti", None, None])

        sm = SessionManager(redis)
        result = await sm.register_session("admin-123", "same-jti", "1.2.3.4")

        assert result["previous_session_invalidated"] is False

    @pytest.mark.asyncio
    async def test_register_session_ip_change_alert(self):
        """Different IP within 5 min window — alert triggered."""
        redis = _make_redis_mock()
        # Existing session: different IP, recent login (10 seconds ago)
        recent_ts = str(time.time() - 10)
        redis.get = AsyncMock(side_effect=[
            None,       # no active JTI
            "5.6.7.8",  # previous IP (different from new)
            recent_ts,  # last_login timestamp
        ])

        sm = SessionManager(redis)
        result = await sm.register_session("admin-123", "new-jti", "1.2.3.4")

        assert result["ip_alert"] is True
        # Alert key should be set
        redis.setex.assert_any_call("auth:alert:admin-123", 300, "1.2.3.4")

    @pytest.mark.asyncio
    async def test_register_session_ip_change_no_alert_after_window(self):
        """Different IP after 5 min window — no alert."""
        redis = _make_redis_mock()
        # Login was 10 minutes ago (600 seconds)
        old_ts = str(time.time() - 600)
        redis.get = AsyncMock(side_effect=[
            None,       # no active JTI
            "5.6.7.8",  # previous IP
            old_ts,     # last_login > 5 min ago
        ])

        sm = SessionManager(redis)
        result = await sm.register_session("admin-123", "new-jti", "1.2.3.4")

        assert result["ip_alert"] is False

    @pytest.mark.asyncio
    async def test_register_session_same_ip_no_alert(self):
        """Same IP on re-login — no alert even if recent."""
        redis = _make_redis_mock()
        recent_ts = str(time.time() - 10)
        redis.get = AsyncMock(side_effect=[
            None,       # no active JTI
            "1.2.3.4",  # same IP as new login
            recent_ts,  # recent
        ])

        sm = SessionManager(redis)
        result = await sm.register_session("admin-123", "new-jti", "1.2.3.4")

        assert result["ip_alert"] is False


# --- validate_session ---


class TestValidateSession:
    @pytest.mark.asyncio
    async def test_validate_session_success(self):
        """Valid session: matching JTI, matching IP, not revoked."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)  # Not revoked
        redis.get = AsyncMock(side_effect=[
            "correct-jti",  # active JTI matches
            "1.2.3.4",      # stored IP matches
        ])

        sm = SessionManager(redis)
        result = await sm.validate_session("admin-123", "correct-jti", "1.2.3.4")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_session_revoked_jti(self):
        """Revoked JTI — session rejected."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=1)  # Token is revoked

        sm = SessionManager(redis)
        result = await sm.validate_session("admin-123", "revoked-jti", "1.2.3.4")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_session_wrong_jti(self):
        """Active JTI doesn't match (superseded) — session rejected."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)  # Not revoked
        redis.get = AsyncMock(side_effect=[
            "other-jti",  # Active JTI is different
        ])

        sm = SessionManager(redis)
        result = await sm.validate_session("admin-123", "my-jti", "1.2.3.4")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_session_no_active_session(self):
        """No active session in Redis — rejected."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)
        redis.get = AsyncMock(return_value=None)  # No active session

        sm = SessionManager(redis)
        result = await sm.validate_session("admin-123", "any-jti", "1.2.3.4")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_session_ip_changed(self):
        """IP changed mid-session — session revoked and rejected."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)
        redis.get = AsyncMock(side_effect=[
            "correct-jti",  # JTI matches (validate_session)
            "1.2.3.4",      # Stored IP differs from request IP (validate_session)
            "correct-jti",  # Active JTI fetched again (invalidate_session)
        ])

        sm = SessionManager(redis)
        result = await sm.validate_session("admin-123", "correct-jti", "5.6.7.8")

        assert result is False
        # The session should have been invalidated
        redis.setex.assert_called_once()
        redis.delete.assert_called_once()


# --- invalidate_session ---


class TestInvalidateSession:
    @pytest.mark.asyncio
    async def test_invalidate_session_with_active_jti(self):
        """Active session exists — JTI revoked and keys deleted."""
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value="active-jti")

        sm = SessionManager(redis)
        await sm.invalidate_session("admin-123")

        # JTI should be revoked
        redis.setex.assert_called_once_with(
            "auth:revoked:active-jti", 1800, "revoked"
        )
        # Session keys should be deleted
        redis.delete.assert_called_once_with(
            "auth:session:admin-123:active",
            "auth:session:admin-123:ip",
        )

    @pytest.mark.asyncio
    async def test_invalidate_session_no_active(self):
        """No active session — just delete keys, no revocation."""
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value=None)

        sm = SessionManager(redis)
        await sm.invalidate_session("admin-123")

        # No setex for revocation (no JTI to revoke)
        redis.setex.assert_not_called()
        # Keys still deleted (idempotent)
        redis.delete.assert_called_once()


# --- is_token_revoked ---


class TestIsTokenRevoked:
    @pytest.mark.asyncio
    async def test_revoked_token(self):
        """Token in revocation set — returns True."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=1)

        sm = SessionManager(redis)
        assert await sm.is_token_revoked("revoked-jti") is True
        redis.exists.assert_called_once_with("auth:revoked:revoked-jti")

    @pytest.mark.asyncio
    async def test_non_revoked_token(self):
        """Token not in revocation set — returns False."""
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)

        sm = SessionManager(redis)
        assert await sm.is_token_revoked("valid-jti") is False
