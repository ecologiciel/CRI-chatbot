"""Encrypted tracking state against disposable Redis and PostgreSQL."""

import asyncio
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
    SecureTrackingStateConflictError,
    SecureTrackingStateError,
    SecureTrackingStateManager,
)
from app.services.orchestrator.tracking_state import TrackingStep

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
            *(
                manager._key_and_record(tenant, phone)[0] + suffix
                for phone in (PHONE, OTHER_PHONE)
                for suffix in ("", ":guard")
            )
        )
        if created:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": ident})
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_state_is_encrypted_bound_to_phone_and_tamper_evident(environment):
    manager, redis, tenant, _ = environment
    state = await manager.get_state(PHONE, tenant)
    assert state.step == TrackingStep.idle
    state.step = TrackingStep.authenticated
    state.identifier = "AB123456"
    state.identifier_type = "cin"
    state.session_token = "a" * 64
    state.dossier_ids = [str(uuid.uuid4())]
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
    await manager.get_state(OTHER_PHONE, tenant)
    await redis.set(other_key, raw, ex=1800)
    with pytest.raises(SecureTrackingStateError):
        await manager.get_state(OTHER_PHONE, tenant)
    await redis.set(key, '{"format":1}', ex=1800)
    with pytest.raises(SecureTrackingStateError):
        await manager.get_state(PHONE, tenant)


@pytest.mark.asyncio
async def test_data_key_rotation_keeps_old_state_readable(environment):
    manager, redis, tenant, kms = environment
    state = await manager.get_state(PHONE, tenant)
    state.step = TrackingStep.awaiting_identifier
    await manager.set_state(PHONE, state, tenant)
    key, _ = manager._key_and_record(tenant, PHONE)
    assert json.loads(await redis.get(key))["key_version"] == 1
    await kms.rotate_key(tenant.id, tenant.slug)
    assert await manager.get_state(PHONE, tenant) == state
    await manager.set_state(PHONE, state, tenant)
    assert json.loads(await redis.get(key))["key_version"] == 2
    await manager.clear_state(PHONE, tenant, expected_state=state)
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
        state = await manager.get_state(PHONE, tenant)
        state.step = TrackingStep.otp_sent
        await manager.set_state(PHONE, state, tenant)
        source, _ = manager._key_and_record(tenant, PHONE)
        destination, _ = manager._key_and_record(other, PHONE)
        await manager.get_state(PHONE, other)
        await redis.set(destination, await redis.get(source), ex=1800)
        with pytest.raises(SecureTrackingStateError):
            await manager.get_state(PHONE, other)
    finally:
        other_key = manager._key_and_record(other, PHONE)[0]
        await redis.delete(other_key, other_key + ":guard")
        if inserted:
            async with sessions.begin() as session:
                await session.execute(
                    text("DELETE FROM public.tenants WHERE id=:id"), {"id": other_id}
                )


@pytest.mark.asyncio
async def test_concurrent_transitions_allow_only_one_writer(environment):
    manager, _, tenant, _ = environment
    first, second = await asyncio.gather(
        manager.get_state(PHONE, tenant), manager.get_state(PHONE, tenant)
    )
    first.step, second.step = TrackingStep.otp_sent, TrackingStep.awaiting_identifier
    results = await asyncio.gather(
        manager.set_state(PHONE, first, tenant),
        manager.set_state(PHONE, second, tenant),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, SecureTrackingStateConflictError) for result in results) == 1
    assert (await manager.get_state(PHONE, tenant)).step in (first.step, second.step)


@pytest.mark.asyncio
async def test_stale_clear_and_expired_state_cannot_replace_new_state(environment):
    manager, redis, tenant, _ = environment
    initial = await manager.get_state(PHONE, tenant)
    initial.step = TrackingStep.otp_sent
    await manager.set_state(PHONE, initial, tenant)
    stale = await manager.get_state(PHONE, tenant)
    latest = await manager.get_state(PHONE, tenant)
    latest.step = TrackingStep.authenticated
    latest.session_token = "b" * 64
    await manager.set_state(PHONE, latest, tenant)
    with pytest.raises(SecureTrackingStateConflictError):
        await manager.clear_state(PHONE, tenant, expected_state=stale)
    assert (await manager.get_state(PHONE, tenant)).session_token == "b" * 64
    key, _ = manager._key_and_record(tenant, PHONE)
    await redis.delete(key)  # Simulate expiration between read and write.
    with pytest.raises(SecureTrackingStateConflictError):
        await manager.set_state(PHONE, latest, tenant)
    assert (await manager.get_state(PHONE, tenant)).step == TrackingStep.idle


@pytest.mark.asyncio
async def test_cleared_state_cannot_be_recreated_by_stale_idle_reader(environment):
    manager, _, tenant, _ = environment
    stale, latest = await asyncio.gather(
        manager.get_state(PHONE, tenant), manager.get_state(PHONE, tenant)
    )
    latest.step = TrackingStep.otp_sent
    await manager.set_state(PHONE, latest, tenant)
    await manager.clear_state(PHONE, tenant, expected_state=latest)
    stale.step = TrackingStep.otp_sent
    with pytest.raises(SecureTrackingStateConflictError):
        await manager.set_state(PHONE, stale, tenant)
