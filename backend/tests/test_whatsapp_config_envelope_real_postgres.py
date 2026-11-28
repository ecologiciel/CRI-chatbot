"""Staged channel-envelope and key-rotation checks on disposable PostgreSQL."""

import json
import os
import secrets
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import CRIDecryptionError
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import open_channel_config, seal_channel_config

URL = os.getenv("TEST_KMS_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_stored_envelope_survives_key_rotation_and_is_tenant_bound():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant, other = uuid.uuid4(), uuid.uuid4()
    slug, other_slug = "wacfg" + tenant.hex, "wacfg" + other.hex
    master = secrets.token_hex(32)
    kms = KMSService(factory, AsyncMock(), master)
    cipher = VersionedEnvelopeService(factory, master)
    config = {"phone_number_id": "123456", "access_token": "synthetic-credential", "verify_token": "synthetic-verifier", "custom": {"secret": "synthetic-extra"}}
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A',:sa,'Test','active'),(:b,'B',:sb,'Test','active')"), {"a": tenant, "b": other, "sa": slug, "sb": other_slug})
        await kms.generate_tenant_key(tenant)
        await kms.generate_tenant_key(other)
        envelope = await seal_channel_config(tenant, config, cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"config": json.dumps(envelope), "id": tenant})
        async with engine.connect() as conn:
            stored = await conn.scalar(text("SELECT whatsapp_config FROM public.tenants WHERE id=:id"), {"id": tenant})
        assert "synthetic-credential" not in repr(stored)
        assert "synthetic-verifier" not in repr(stored)
        assert "synthetic-extra" not in repr(stored)
        assert await open_channel_config(tenant, stored, cipher) == config
        with pytest.raises(CRIDecryptionError):
            await open_channel_config(other, stored, cipher)
        await kms.rotate_key(tenant, slug)
        assert await open_channel_config(tenant, stored, cipher) == config
        new_envelope = await seal_channel_config(tenant, config, cipher)
        assert new_envelope["_envelope"]["version"] == 2
        assert await open_channel_config(tenant, new_envelope, cipher) == config
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id IN (:a,:b)"), {"a": tenant, "b": other})
        await engine.dispose()
