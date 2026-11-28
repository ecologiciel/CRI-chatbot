"""Staged atomic OTP primitive; the public tracking route remains disabled.

This primitive does not send codes or establish a delivery guarantee. It must
not be connected to the conversation flow until delivery and session handling
have separately been reviewed and tested.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError
from app.core.metrics import OTP_ATTEMPTS, OTP_FAILURES, OTP_SUCCESS, RATE_LIMIT_TRIGGERED
from app.core.redis import get_redis
from app.services.dossier.otp import ATTEMPT_WINDOW, MAX_OTP_ATTEMPTS, OTP_TTL, DossierOTPService

_PHONE = re.compile(r"\+[1-9][0-9]{6,14}\Z", re.ASCII)
_CODE = re.compile(r"[0-9]{6}\Z", re.ASCII)

# Each script runs entirely within Redis. A generation budget is independent
# of the verification budget; creating a new code cannot remove that budget.
_GENERATE = """
local count = redis.call('GET', KEYS[2])
if count then
  local parsed = tonumber(count)
  if not parsed or parsed < 0 or parsed ~= math.floor(parsed) or redis.call('TTL', KEYS[2]) < 0 then
    return redis.error_reply('invalid OTP generation budget')
  end
  if parsed >= tonumber(ARGV[2]) then return 0 end
  redis.call('INCR', KEYS[2])
else
  redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[4])
redis.call('DEL', KEYS[3])
return 1
"""

_VERIFY = """
local stored = redis.call('GET', KEYS[1])
if not stored then return 0 end
local ttl = redis.call('PTTL', KEYS[1])
if ttl <= 0 then return 0 end
local count = redis.call('GET', KEYS[2])
if count then
  local parsed = tonumber(count)
  if not parsed or parsed < 0 or parsed ~= math.floor(parsed) or redis.call('PTTL', KEYS[2]) < 0 then
    return redis.error_reply('invalid OTP verification budget')
  end
  if parsed >= tonumber(ARGV[2]) then redis.call('DEL', KEYS[1]); return 0 end
end
if stored == ARGV[1] then
  redis.call('DEL', KEYS[1], KEYS[2])
  return 1
end
local attempts = redis.call('INCR', KEYS[2])
if attempts == 1 then redis.call('PEXPIRE', KEYS[2], ttl) end
if attempts >= tonumber(ARGV[2]) then redis.call('DEL', KEYS[1]) end
return 0
"""


class AtomicDossierOTPService(DossierOTPService):
    """One-time codes with atomic generation and verification budgets."""

    @staticmethod
    def _redis_key(tenant, key_type, identifier):
        # Slugs can be reused after removal; bind both OTPs and inherited
        # sessions to the immutable institution identity as well.
        return f"{tenant.slug}:{key_type}:{tenant.id.hex}:{identifier}"

    @staticmethod
    def _digest(phone, code, tenant):
        if not isinstance(phone, str) or not _PHONE.fullmatch(phone):
            raise ValueError("Invalid phone number")
        try:
            key = bytes.fromhex(get_settings().kms_master_key)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("OTP key unavailable") from exc
        if len(key) != 32:
            raise RuntimeError("OTP key unavailable")
        message = b"dossier-otp-v1\0" + tenant.id.bytes + b"\0" + phone.encode("ascii") + b"\0" + code.encode("ascii")
        return "v1:" + hmac.new(key, message, hashlib.sha256).hexdigest()

    async def generate_otp(self, phone, tenant):
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = self._digest(phone, code, tenant)
        redis = get_redis()
        result = await redis.eval(
            _GENERATE, 3,
            self._redis_key(tenant, "dossier_otp", phone),
            self._redis_key(tenant, "dossier_otp_attempts", phone),
            self._redis_key(tenant, "dossier_otp_verify_attempts", phone),
            digest, MAX_OTP_ATTEMPTS, ATTEMPT_WINDOW, OTP_TTL,
        )
        OTP_ATTEMPTS.labels(tenant=tenant.slug).inc()
        if result != 1:
            OTP_FAILURES.labels(tenant=tenant.slug).inc()
            RATE_LIMIT_TRIGGERED.labels(tenant=tenant.slug, level="otp").inc()
            raise RateLimitExceededError("OTP rate limit exceeded. Try again later.")
        await self._audit(tenant, "otp_generate", phone)
        return code

    async def verify_otp(self, phone, otp_code, tenant):
        # Invalid input consumes a verification attempt if a code is active;
        # it can never match the fixed-format stored digest.
        valid_format = isinstance(otp_code, str) and _CODE.fullmatch(otp_code)
        digest = self._digest(phone, otp_code if valid_format else "invalid", tenant)
        redis = get_redis()
        result = await redis.eval(
            _VERIFY, 2,
            self._redis_key(tenant, "dossier_otp", phone),
            self._redis_key(tenant, "dossier_otp_verify_attempts", phone),
            digest, MAX_OTP_ATTEMPTS,
        )
        OTP_ATTEMPTS.labels(tenant=tenant.slug).inc()
        if result == 1:
            OTP_SUCCESS.labels(tenant=tenant.slug).inc()
            await self._audit(tenant, "otp_verify_success", phone)
            return True
        OTP_FAILURES.labels(tenant=tenant.slug).inc()
        await self._audit(tenant, "otp_verify_fail", phone, details={"reason": "invalid_or_expired"})
        return False
