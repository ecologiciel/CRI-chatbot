"""Concurrency and isolation tests on a disposable Redis, without FLUSHDB."""
import asyncio
import hashlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.exceptions import RateLimitExceededError
from app.core.tenant import TenantContext
from app.services.dossier import otp_atomic
from app.services.dossier.otp_atomic import AtomicDossierOTPService

URL = os.getenv("TEST_ATOMIC_OTP_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable Redis")
PHONE = "+212600000001"


@pytest_asyncio.fixture
async def environment(monkeypatch):
    parsed = urlparse(URL)
    if parsed.hostname not in ("otp-redis", "127.0.0.1") or parsed.path != "/15":
        raise RuntimeError("Refusing Redis endpoint outside the isolated OTP fixture")
    redis = Redis.from_url(URL)
    slug = "otpfixture" + uuid.uuid4().hex
    tenant = TenantContext(id=uuid.uuid4(), slug=slug, name="Fixture", status="active", whatsapp_config=None)
    service = AtomicDossierOTPService()
    service._audit = AsyncMock()
    monkeypatch.setattr(otp_atomic, "get_redis", lambda: redis)
    monkeypatch.setattr(otp_atomic, "get_settings", lambda: SimpleNamespace(kms_master_key="6a" * 32))
    try:
        yield service, redis, tenant
    finally:
        keys = [service._redis_key(tenant, kind, PHONE) for kind in ("dossier_otp", "dossier_otp_attempts", "dossier_otp_verify_attempts")]
        await redis.delete(*keys)
        await redis.aclose()


@pytest.mark.asyncio
async def test_concurrent_verification_consumes_code_once(environment):
    service, redis, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    stored = await redis.get(service._redis_key(tenant, "dossier_otp", PHONE))
    assert stored != code.encode()
    assert stored != hashlib.sha256(code.encode()).hexdigest().encode()
    outcomes = await asyncio.gather(*(service.verify_otp(PHONE, code, tenant) for _ in range(30)))
    assert sum(outcomes) == 1


@pytest.mark.asyncio
async def test_concurrent_wrong_attempts_cannot_bruteforce_or_reuse(environment):
    service, _, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    invalid = "000000" if code != "000000" else "999999"
    assert not any(await asyncio.gather(*(service.verify_otp(PHONE, invalid, tenant) for _ in range(20))))
    assert await service.verify_otp(PHONE, code, tenant) is False


@pytest.mark.asyncio
async def test_generation_budget_is_atomic_and_not_bypassed_by_new_code(environment):
    service, _, tenant = environment
    outcomes = await asyncio.gather(*(service.generate_otp(PHONE, tenant) for _ in range(15)), return_exceptions=True)
    assert sum(isinstance(value, str) for value in outcomes) == 3
    assert sum(isinstance(value, RateLimitExceededError) for value in outcomes) == 12
    with pytest.raises(RateLimitExceededError):
        await service.generate_otp(PHONE, tenant)


@pytest.mark.asyncio
async def test_expired_codes_and_missing_key_are_rejected(environment, monkeypatch):
    service, redis, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    await redis.pexpire(service._redis_key(tenant, "dossier_otp", PHONE), 20)
    await asyncio.sleep(0.05)
    assert await service.verify_otp(PHONE, code, tenant) is False
    monkeypatch.setattr(otp_atomic, "get_settings", lambda: SimpleNamespace(kms_master_key=""))
    with pytest.raises(RuntimeError, match="OTP key unavailable"):
        await service.generate_otp(PHONE, tenant)


@pytest.mark.asyncio
async def test_corrupt_or_persistent_budget_fails_closed(environment):
    service, redis, tenant = environment
    budget = service._redis_key(tenant, "dossier_otp_attempts", PHONE)
    await redis.set(budget, "1")
    with pytest.raises(ResponseError, match="invalid OTP generation budget"):
        await service.generate_otp(PHONE, tenant)
    assert await redis.get(service._redis_key(tenant, "dossier_otp", PHONE)) is None


@pytest.mark.asyncio
async def test_code_is_bound_to_institution_id_even_if_slug_is_reused(environment):
    service, _, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    replacement = TenantContext(id=uuid.uuid4(), slug=tenant.slug, name="Replacement", status="active", whatsapp_config=None)
    assert await service.verify_otp(PHONE, code, replacement) is False
    assert await service.verify_otp(PHONE, code, tenant) is True


@pytest.mark.asyncio
async def test_malformed_input_uses_attempt_budget_but_correct_code_can_still_work(environment):
    service, _, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    assert await service.verify_otp(PHONE, "12", tenant) is False
    assert await service.verify_otp(PHONE, "é" * 6, tenant) is False
    assert await service.verify_otp(PHONE, code, tenant) is True


@pytest.mark.asyncio
async def test_persistent_verification_counter_is_rejected(environment):
    service, redis, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    key = service._redis_key(tenant, "dossier_otp_verify_attempts", PHONE)
    await redis.set(key, "1")
    with pytest.raises(ResponseError, match="invalid OTP verification budget"):
        await service.verify_otp(PHONE, code, tenant)
