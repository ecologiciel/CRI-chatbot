"""Encrypted tracking state against disposable Redis and PostgreSQL."""

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.crypto.kms import KMSService
from app.services.orchestrator import secure_tracking_state as secure
from app.services.orchestrator.secure_tracking_state import (
    SecureTrackingStateError,
    SecureTrackingStateManager,
)
from app.services.orchestrator.tracking_state import TrackingStep, TrackingUserState

DB_URL = os.getenv("TEST_TRACKING_STATE_DB_URL")
REDIS_URL = os.getenv("TEST_ATOMIC_OTP_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL or not REDIS_URL, reason="requires isolated Redis and PostgreSQL"
)
PHONE = "+212600000001"
OTHER_PHONE = "+212600000002"


@pytest_asyncio.fixture
async def environment(monkeypatch):
    db_url, redis_url = make_url(DB_URL), urlparse(REDIS_URL)
    if not db_url.database or not db_url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing non-fixture PostgreSQL")
    if redis_url.hostname not in ("otp-redis", "127.0.0.1") or redis_url.path != "/15":
        raise RuntimeError("Refusing non-fixture Redis")
    engine = create_async_engine(DB_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(REDIS_URL)
    ident = uuid.uuid4()
    tenant = TenantContext(
        id=ident, slug="fixture" + ident.hex, name="Fixture", status="active", whatsapp_config=None
    )
    master = "6a" * 32
    manager = SecureTrackingStateManager()
    monkeypatch.setattr(secure, "get_redis", lambda: redis)
    monkeypatch.setattr(secure, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(secure, "get_settings", lambda: SimpleNamespace(kms_master_key=master))
    created = False
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))) == db_url.database
            await conn.execute(
                text(
                    "INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"
                ),
                {"id": ident, "slug": tenant.slug},
            )
            created = True
        kms = KMSService(sessions, AsyncMock(), master)
        await kms.generate_tenant_key(ident)
        yield manager, redis, tenant, kms
    finally:
        await redis.delete(
            *(manager._key_and_record(tenant, phone)[0] for phone in (PHONE, OTHER_PHONE))
        )
        if created:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": ident})
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_state_is_encrypted_bound_to_phone_and_tamper_evident(environment):
    manager, redis, tenant, _ = environment
    state = TrackingUserState(
        step=TrackingStep.authenticated,
        identifier="AB123456",
        identifier_type="cin",
        session_token="a" * 64,
        dossier_ids=[str(uuid.uuid4())],
    )
    assert (await manager.get_state(PHONE, tenant)).step == TrackingStep.idle
    await manager.set_state(PHONE, state, tenant)
    key, _ = manager._key_and_record(tenant, PHONE)
    raw = await redis.get(key)
    assert (
        PHONE not in key
        and state.identifier.encode() not in raw
        and state.session_token.encode() not in raw
    )
    assert (await manager.get_state(PHONE, tenant)) == state
    assert 0 < await redis.ttl(key) <= 1800
    other_key, _ = manager._key_and_record(tenant, OTHER_PHONE)
    await redis.set(other_key, raw, ex=1800)
    with pytest.raises(SecureTrackingStateError):
        await manager.get_state(OTHER_PHONE, tenant)
    await redis.set(key, '{"format":1}', ex=1800)
    with pytest.raises(SecureTrackingStateError):
        await manager.get_state(PHONE, tenant)


@pytest.mark.asyncio
async def test_data_key_rotation_keeps_old_state_readable(environment):
    manager, redis, tenant, kms = environment
    state = TrackingUserState(step=TrackingStep.awaiting_identifier)
    await manager.set_state(PHONE, state, tenant)
    key, _ = manager._key_and_record(tenant, PHONE)
    assert json.loads(await redis.get(key))["key_version"] == 1
    await kms.rotate_key(tenant.id, tenant.slug)
    assert await manager.get_state(PHONE, tenant) == state
    await manager.set_state(PHONE, state, tenant)
    assert json.loads(await redis.get(key))["key_version"] == 2
    await manager.clear_state(PHONE, tenant)
    assert (await manager.get_state(PHONE, tenant)).step == TrackingStep.idle


@pytest.mark.asyncio
async def test_ciphertext_cannot_be_transferred_between_institutions(environment):
    manager, redis, tenant, kms = environment
    other_id = uuid.uuid4()
    other = TenantContext(
        id=other_id,
        slug="fixture" + other_id.hex,
        name="Other",
        status="active",
        whatsapp_config=None,
    )
    sessions = secure.get_session_factory()
    inserted = False
    try:
        async with sessions.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Other',:slug,'Test','active')"
                ),
                {"id": other_id, "slug": other.slug},
            )
            inserted = True
        await kms.generate_tenant_key(other_id)
        await manager.set_state(PHONE, TrackingUserState(step=TrackingStep.otp_sent), tenant)
        source, _ = manager._key_and_record(tenant, PHONE)
        destination, _ = manager._key_and_record(other, PHONE)
        await redis.set(destination, await redis.get(source), ex=1800)
        with pytest.raises(SecureTrackingStateError):
            await manager.get_state(PHONE, other)
    finally:
        await redis.delete(manager._key_and_record(other, PHONE)[0])
        if inserted:
            async with sessions.begin() as session:
                await session.execute(
                    text("DELETE FROM public.tenants WHERE id=:id"), {"id": other_id}
                )
