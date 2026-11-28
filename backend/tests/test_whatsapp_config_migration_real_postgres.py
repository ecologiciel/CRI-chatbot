"""Transactional staged config conversion on disposable PostgreSQL."""

import json
import os
import secrets
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import CRIDecryptionError
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import open_channel_config
from app.services.whatsapp.config_migration import seal_existing_channel_configs

URL = os.getenv("TEST_KMS_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_migration_is_atomic_audited_and_idempotent():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = sorted([uuid.uuid4(), uuid.uuid4()])
    first, second = ids
    suffix = uuid.uuid4().hex[:18]
    slugs = ["wama" + suffix, "wamb" + suffix]
    configs = [
        {"phone_number_id": "83450001", "access_token": "synthetic-secret-one"},
        {"phone_number_id": "83450002", "verify_token": "synthetic-secret-two"},
    ]
    master = secrets.token_hex(32)
    cipher = VersionedEnvelopeService(factory, master)
    kms = KMSService(factory, AsyncMock(), master)
    constraint = False
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            for tenant_id, slug, config in zip(ids, slugs, configs, strict=True):
                await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture',:slug,'Test','active',CAST(:config AS jsonb))"), {"id": tenant_id, "slug": slug, "config": json.dumps(config)})
        await kms.generate_tenant_key(first)
        with pytest.raises(CRIDecryptionError):
            await seal_existing_channel_configs(factory, cipher)
        async with engine.connect() as conn:
            configs_after = (await conn.execute(text("SELECT whatsapp_config FROM public.tenants WHERE id IN (:a,:b) ORDER BY id"), {"a": first, "b": second})).scalars().all()
            assert configs_after == configs
        await kms.generate_tenant_key(second)
        with pytest.raises(RuntimeError, match="exceeds"):
            await seal_existing_channel_configs(factory, cipher, max_tenants=1)
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_wa_seal CHECK (action <> 'wa_config_sealed') NOT VALID"))
            constraint = True
        with pytest.raises(IntegrityError):
            await seal_existing_channel_configs(factory, cipher)
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT count(*) FROM public.tenants WHERE id IN (:a,:b) AND whatsapp_config ? 'access_token'"), {"a": first, "b": second})) == 1
            await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_wa_seal"))
            constraint = False
        assert await seal_existing_channel_configs(factory, cipher) == {"sealed": 2, "already_sealed": 0, "without_config": 0}
        assert await seal_existing_channel_configs(factory, cipher) == {"sealed": 0, "already_sealed": 2, "without_config": 0}
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT id,whatsapp_config FROM public.tenants WHERE id IN (:a,:b) ORDER BY id"), {"a": first, "b": second})).all()
            count = await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE action='wa_config_sealed' AND tenant_slug IN (:a,:b)"), {"a": slugs[0], "b": slugs[1]})
        assert count == 2
        for row, original in zip(rows, configs, strict=True):
            assert "synthetic-secret" not in repr(row.whatsapp_config)
            assert await open_channel_config(row.id, row.whatsapp_config, cipher) == original
    finally:
        async with engine.begin() as conn:
            if constraint:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_wa_seal"))
            await conn.execute(text("DELETE FROM public.tenants WHERE id IN (:a,:b)"), {"a": first, "b": second})
        await engine.dispose()
