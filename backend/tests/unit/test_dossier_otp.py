"""Unit tests for DossierOTPService -- Wave 23A.

Tests cover: OTP generation, verification (anti-replay), rate limiting,
session lifecycle (create/validate/invalidate), audit trail, and tenant isolation.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import RateLimitExceededError
from app.services.dossier.otp import (
    ATTEMPT_WINDOW,
    MAX_OTP_ATTEMPTS,
    OTP_TTL,
    SESSION_TTL,
    DossierOTPService,
)
from tests.unit.conftest import TEST_PHONE, make_tenant

# -- Patch targets (where the name is looked up, not where defined) ---------

_REDIS = "app.services.dossier.otp.get_redis"
_AUDIT = "app.services.dossier.otp.get_audit_service"


# -- Helpers ----------------------------------------------------------------


def _make_redis(
    *,
    otp_hash: str | None = None,
    attempts: int | None = None,
    session_json: str | None = None,
) -> AsyncMock:
    """Create a mock Redis configured for OTP tests.

    Args:
        otp_hash: SHA-256 hash to return for dossier_otp keys.
        attempts: Integer count to return for dossier_otp_attempts keys.
        session_json: JSON string to return for dossier_session keys.
    """
    redis = AsyncMock()

    async def _get(key: str) -> bytes | None:
        if "dossier_otp_attempts:" in key and attempts is not None:
            return str(attempts).encode()
        if "dossier_otp:" in key and otp_hash is not None:
            return otp_hash.encode()
        if "dossier_session:" in key and session_json is not None:
            return session_json.encode()
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=(attempts or 0) + 1)
    redis.expire = AsyncMock()
    redis.ttl = AsyncMock(return_value=600)
    return redis


def _mock_audit() -> AsyncMock:
    """Create a mock AuditService."""
    audit = AsyncMock()
    audit.log_action = AsyncMock()
    return audit


# -- TestGenerateOTP --------------------------------------------------------


class TestGenerateOTP:
    """Tests for DossierOTPService.generate_otp."""

    @pytest.mark.asyncio
    async def test_returns_6_digits(self, tenant_context):
        """OTP must be exactly 6 digits (100000-999999)."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            otp = await svc.generate_otp(TEST_PHONE, tenant_context)

        assert len(otp) == 6
        assert otp.isdigit()
        assert 100000 <= int(otp) <= 999999

    @pytest.mark.asyncio
    async def test_stores_hash_not_plaintext(self, tenant_context):
        """Redis must receive the SHA-256 hash, NEVER the plaintext OTP."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            otp = await svc.generate_otp(TEST_PHONE, tenant_context)

        # Extract the value passed to redis.set()
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        stored_value = call_args[0][1]

        # Stored value must be the SHA-256 hash, not the OTP
        expected_hash = hashlib.sha256(otp.encode()).hexdigest()
        assert stored_value == expected_hash
        assert otp not in stored_value

    @pytest.mark.asyncio
    async def test_sets_correct_ttl(self, tenant_context):
        """OTP key must have TTL of 300 seconds (5 min)."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.generate_otp(TEST_PHONE, tenant_context)

        call_kwargs = redis.set.call_args
        assert call_kwargs[1]["ex"] == OTP_TTL

    @pytest.mark.asyncio
    async def test_rate_limited_raises(self, tenant_context):
        """Must raise RateLimitExceededError when attempts >= 3."""
        redis = _make_redis(attempts=MAX_OTP_ATTEMPTS)
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            with pytest.raises(RateLimitExceededError):
                await svc.generate_otp(TEST_PHONE, tenant_context)

    @pytest.mark.asyncio
    async def test_increments_attempt_counter(self, tenant_context):
        """Must increment the attempt counter on each generation."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.generate_otp(TEST_PHONE, tenant_context)

        expected_key = f"{tenant_context.slug}:dossier_otp_attempts:{TEST_PHONE}"
        redis.incr.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_first_attempt_sets_expire(self, tenant_context):
        """First attempt (count=1) must set EXPIRE on attempts key."""
        redis = _make_redis()
        redis.incr = AsyncMock(return_value=1)
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.generate_otp(TEST_PHONE, tenant_context)

        expected_key = f"{tenant_context.slug}:dossier_otp_attempts:{TEST_PHONE}"
        redis.expire.assert_called_once_with(expected_key, ATTEMPT_WINDOW)


# -- TestVerifyOTP ----------------------------------------------------------


class TestVerifyOTP:
    """Tests for DossierOTPService.verify_otp."""

    @pytest.mark.asyncio
    async def test_success_returns_true(self, tenant_context):
        """Valid OTP must return True."""
        otp_code = "123456"
        otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        redis = _make_redis(otp_hash=otp_hash)
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            result = await svc.verify_otp(TEST_PHONE, otp_code, tenant_context)

        assert result is True

    @pytest.mark.asyncio
    async def test_success_deletes_key_anti_replay(self, tenant_context):
        """Anti-replay: OTP key must be deleted on successful verification."""
        otp_code = "123456"
        otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        redis = _make_redis(otp_hash=otp_hash)
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.verify_otp(TEST_PHONE, otp_code, tenant_context)

        expected_key = f"{tenant_context.slug}:dossier_otp:{TEST_PHONE}"
        redis.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_wrong_code_returns_false(self, tenant_context):
        """Wrong OTP code must return False, key NOT deleted."""
        correct_hash = hashlib.sha256("123456".encode()).hexdigest()
        redis = _make_redis(otp_hash=correct_hash)
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            result = await svc.verify_otp(TEST_PHONE, "999999", tenant_context)

        assert result is False
        redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_returns_false(self, tenant_context):
        """Expired OTP (key absent) must return False."""
        redis = _make_redis()  # No otp_hash = key not found
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            result = await svc.verify_otp(TEST_PHONE, "123456", tenant_context)

        assert result is False


# -- TestRateLimiting -------------------------------------------------------


class TestRateLimiting:
    """Tests for DossierOTPService.is_rate_limited."""

    @pytest.mark.asyncio
    async def test_at_limit_returns_true(self, tenant_context):
        """Exactly at limit (3 attempts) must return True."""
        redis = _make_redis(attempts=3)
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.is_rate_limited(tenant_context, TEST_PHONE)

        assert result is True

    @pytest.mark.asyncio
    async def test_under_limit_returns_false(self, tenant_context):
        """Under limit (2 attempts) must return False."""
        redis = _make_redis(attempts=2)
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.is_rate_limited(tenant_context, TEST_PHONE)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_attempts_returns_false(self, tenant_context):
        """No attempts key (None) must return False."""
        redis = _make_redis()  # attempts=None -> get returns None
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.is_rate_limited(tenant_context, TEST_PHONE)

        assert result is False


# -- TestDossierSession -----------------------------------------------------


class TestDossierSession:
    """Tests for session create/validate/invalidate lifecycle."""

    @pytest.mark.asyncio
    async def test_create_returns_64_char_hex(self, tenant_context):
        """Session token must be 64-char hex string (32 bytes)."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            token = await svc.create_dossier_session(TEST_PHONE, tenant_context)

        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    @pytest.mark.asyncio
    async def test_create_stores_with_correct_ttl(self, tenant_context):
        """Session must be stored with TTL of 1800 seconds."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.create_dossier_session(TEST_PHONE, tenant_context)

        call_kwargs = redis.set.call_args
        assert call_kwargs[1]["ex"] == SESSION_TTL

    @pytest.mark.asyncio
    async def test_validate_success_refreshes_ttl(self, tenant_context):
        """Valid session must refresh TTL (sliding window)."""
        token = "a" * 64
        session_data = json.dumps({
            "token": token,
            "phone": TEST_PHONE,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        redis = _make_redis(session_json=session_data)
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.validate_dossier_session(
                TEST_PHONE, token, tenant_context,
            )

        assert result is True
        expected_key = f"{tenant_context.slug}:dossier_session:{TEST_PHONE}"
        redis.expire.assert_called_once_with(expected_key, SESSION_TTL)

    @pytest.mark.asyncio
    async def test_validate_wrong_token_returns_false(self, tenant_context):
        """Wrong session token must return False."""
        session_data = json.dumps({
            "token": "a" * 64,
            "phone": TEST_PHONE,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        redis = _make_redis(session_json=session_data)
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.validate_dossier_session(
                TEST_PHONE, "b" * 64, tenant_context,
            )

        assert result is False
        redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_expired_returns_false(self, tenant_context):
        """Expired session (key absent) must return False."""
        redis = _make_redis()  # No session_json -> returns None
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis):
            result = await svc.validate_dossier_session(
                TEST_PHONE, "a" * 64, tenant_context,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_deletes_key(self, tenant_context):
        """Invalidation must delete the session key."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.invalidate_session(TEST_PHONE, tenant_context)

        expected_key = f"{tenant_context.slug}:dossier_session:{TEST_PHONE}"
        redis.delete.assert_called_once_with(expected_key)


# -- TestAuditTrail ---------------------------------------------------------


class TestAuditTrail:
    """Tests for audit logging on each OTP operation."""

    @pytest.mark.asyncio
    async def test_generate_logs_audit(self, tenant_context):
        """OTP generation must log audit with action=otp_generate."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.generate_otp(TEST_PHONE, tenant_context)

        audit.log_action.assert_called_once()
        logged = audit.log_action.call_args[0][0]
        assert logged.action == "otp_generate"
        assert logged.tenant_slug == tenant_context.slug
        assert logged.resource_type == "dossier_otp"

    @pytest.mark.asyncio
    async def test_verify_success_logs_audit(self, tenant_context):
        """Successful verification must log action=otp_verify_success."""
        otp_code = "123456"
        otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        redis = _make_redis(otp_hash=otp_hash)
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.verify_otp(TEST_PHONE, otp_code, tenant_context)

        audit.log_action.assert_called_once()
        logged = audit.log_action.call_args[0][0]
        assert logged.action == "otp_verify_success"

    @pytest.mark.asyncio
    async def test_verify_fail_logs_audit_with_reason(self, tenant_context):
        """Failed verification must log action=otp_verify_fail with reason."""
        redis = _make_redis()  # No OTP stored -> expired
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.verify_otp(TEST_PHONE, "123456", tenant_context)

        audit.log_action.assert_called_once()
        logged = audit.log_action.call_args[0][0]
        assert logged.action == "otp_verify_fail"
        assert logged.details["reason"] == "expired_or_missing"


# -- TestTenantIsolation ----------------------------------------------------


class TestTenantIsolation:
    """Tests ensuring Redis keys are properly scoped to tenant."""

    @pytest.mark.asyncio
    async def test_keys_use_tenant_slug(self, tenant_context):
        """Redis keys must contain the tenant slug as prefix."""
        redis = _make_redis()
        audit = _mock_audit()
        svc = DossierOTPService()

        with patch(_REDIS, return_value=redis), patch(_AUDIT, return_value=audit):
            await svc.generate_otp(TEST_PHONE, tenant_context)

        # Verify the OTP key includes tenant slug
        otp_key = redis.set.call_args[0][0]
        assert otp_key.startswith(f"{tenant_context.slug}:")
        assert "dossier_otp:" in otp_key

    @pytest.mark.asyncio
    async def test_different_tenants_different_keys(self):
        """Two tenants must produce different Redis keys for the same phone."""
        tenant_a = make_tenant(slug="rabat")
        tenant_b = make_tenant(slug="tanger")
        svc = DossierOTPService()

        key_a = svc._redis_key(tenant_a, "dossier_otp", TEST_PHONE)
        key_b = svc._redis_key(tenant_b, "dossier_otp", TEST_PHONE)

        assert key_a != key_b
        assert key_a.startswith("rabat:")
        assert key_b.startswith("tanger:")
