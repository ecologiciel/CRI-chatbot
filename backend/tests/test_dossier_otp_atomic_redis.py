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
from app.services.dossier import otp
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
    monkeypatch.setattr(otp, "get_redis", lambda: redis)
    monkeypatch.setattr(otp_atomic, "get_settings", lambda: SimpleNamespace(kms_master_key="6a" * 32))
    try:
        yield service, redis, tenant
    finally:
        keys = [service._redis_key(tenant, kind, PHONE) for kind in ("dossier_otp", "dossier_otp_attempts", "dossier_otp_verify_attempts", "dossier_session")]
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
    service, redis, tenant = environment
    code = await service.generate_otp(PHONE, tenant)
    replacement = TenantContext(id=uuid.uuid4(), slug=tenant.slug, name="Replacement", status="active", whatsapp_config=None)
    try:
        assert await service.verify_otp(PHONE, code, replacement) is False
        assert await service.verify_otp(PHONE, code, tenant) is True
        assert await service.verify_otp(PHONE, await service.generate_otp(PHONE, replacement), replacement)
    finally:
        await redis.delete(*(service._redis_key(replacement, kind, PHONE) for kind in ("dossier_otp", "dossier_otp_attempts", "dossier_otp_verify_attempts")))


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


@pytest.mark.asyncio
async def test_factory_service_runs_atomic_protocol_on_real_redis(environment, monkeypatch):
    _, _, tenant = environment
    monkeypatch.setattr(otp, "_dossier_otp_service", None)
    service = otp.get_dossier_otp_service()
    service._audit = AsyncMock()
    code = await service.generate_otp(PHONE, tenant)
    outcomes = await asyncio.gather(*(service.verify_otp(PHONE, code, tenant) for _ in range(10)))
    assert sum(outcomes) == 1


@pytest.mark.asyncio
async def test_tenant_and_phone_budgets_are_independent(environment):
    service, redis, tenant = environment
    other = TenantContext(id=uuid.uuid4(), slug="otpfixture" + uuid.uuid4().hex, name="Other", status="active", whatsapp_config=None)
    phone_b = "+212600000002"
    try:
        for _ in range(3):
            await service.generate_otp(PHONE, tenant)
        with pytest.raises(RateLimitExceededError):
            await service.generate_otp(PHONE, tenant)
        tenant_b_code = await service.generate_otp(PHONE, other)
        phone_b_code = await service.generate_otp(phone_b, tenant)
        assert await service.verify_otp(PHONE, tenant_b_code, other)
        assert await service.verify_otp(phone_b, phone_b_code, tenant)
    finally:
        keys = [
            service._redis_key(t, kind, phone)
            for t, phone in ((other, PHONE), (tenant, phone_b))
            for kind in ("dossier_otp", "dossier_otp_attempts", "dossier_otp_verify_attempts")
        ]
        await redis.delete(*keys)


@pytest.mark.asyncio
async def test_replaced_session_cannot_validate_and_token_is_not_stored(environment):
    service, redis, tenant = environment
    first = await service.create_dossier_session(PHONE, tenant)
    key = service._redis_key(tenant, "dossier_session", PHONE)
    stored = await redis.get(key)
    assert first.encode() not in stored
    assert PHONE.encode() not in stored
    assert await service.validate_dossier_session(PHONE, first, tenant)
    second = await service.create_dossier_session(PHONE, tenant)
    assert first != second
    await redis.expire(key, 10)
    assert not await service.validate_dossier_session(PHONE, first, tenant)
    assert 0 < await redis.ttl(key) <= 10
    assert await service.validate_dossier_session(PHONE, second, tenant)
    assert await redis.ttl(key) > 1700
    await service.invalidate_session(PHONE, tenant)
    assert not await service.validate_dossier_session(PHONE, second, tenant)


@pytest.mark.asyncio
async def test_session_with_missing_expiration_is_rejected(environment):
    service, redis, tenant = environment
    token = await service.create_dossier_session(PHONE, tenant)
    key = service._redis_key(tenant, "dossier_session", PHONE)
    await redis.persist(key)
    assert not await service.validate_dossier_session(PHONE, token, tenant)
