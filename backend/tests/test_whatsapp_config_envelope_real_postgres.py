"""Staged channel-envelope and key-rotation checks on disposable PostgreSQL."""

import json
import os
import secrets
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.notifications import update_template
from app.api.v1.tenant import get_tenant, update_tenant
from app.core.exceptions import CRIDecryptionError, CRIEncryptionError
from app.core.tenant import TenantResolver
from app.schemas.notification import NotificationTemplateUpdate
from app.schemas.tenant import TenantUpdate
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
        with (
            patch("app.core.tenant.get_session_factory", return_value=factory),
            patch("app.core.config.get_settings", return_value=SimpleNamespace(
                kms_master_key=master, whatsapp_config_require_encryption=True
            )),
        ):
            for resolved in (
                await TenantResolver.from_phone_number_id("123456"),
                await TenantResolver.from_tenant_id_header(str(tenant)),
                await TenantResolver.from_slug(slug),
            ):
                assert resolved.id == tenant and resolved.whatsapp_config == config
            altered = dict(stored, phone_number_id="999999")
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"config": json.dumps(altered), "id": tenant})
            with pytest.raises(CRIDecryptionError):
                await TenantResolver.from_phone_number_id("999999")
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"config": json.dumps(envelope), "id": tenant})
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


@pytest.mark.asyncio
async def test_sealed_channel_api_updates_preserve_encryption_and_hide_credentials():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    slug = "waapi" + tenant_id.hex
    master = secrets.token_hex(32)
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    kms = KMSService(factory, AsyncMock(), master)
    cipher = VersionedEnvelopeService(factory, master)
    config = {"phone_number_id": "843210", "access_token": "synthetic-before", "verify_token": "synthetic-verifier", "business_account_id": "fixture-biz"}
    admin = MagicMock(role="super_admin", sub=str(uuid.uuid4()))
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"), {"id": tenant_id, "slug": slug})
        await kms.generate_tenant_key(tenant_id)
        envelope = await seal_channel_config(tenant_id, config, cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"config": json.dumps(envelope), "id": tenant_id})
        with (
            patch("app.api.v1.tenant.get_session_factory", return_value=factory),
            patch("app.api.v1.tenant.get_settings", return_value=SimpleNamespace(
                kms_master_key="", whatsapp_config_require_encryption=True
            )),
        ):
            with pytest.raises(CRIEncryptionError):
                await update_tenant(tenant_id, TenantUpdate(name="must-roll-back", whatsapp_config=config), admin)
        async with engine.connect() as conn:
            unchanged = (await conn.execute(text("SELECT name, whatsapp_config FROM public.tenants WHERE id=:id"), {"id": tenant_id})).one()
            assert unchanged.name == "Fixture" and unchanged.whatsapp_config == envelope
        with (
            patch("app.core.tenant.get_session_factory", return_value=factory),
            patch("app.api.v1.tenant.get_session_factory", return_value=factory),
            patch("app.api.v1.notifications.get_session_factory", return_value=factory),
            patch("app.core.config.get_settings", return_value=settings),
            patch("app.api.v1.tenant.get_settings", return_value=settings),
            patch("app.api.v1.notifications.get_settings", return_value=settings),
            patch("app.api.v1.notifications.get_redis", return_value=AsyncMock()),
            patch("app.api.v1.notifications.get_audit_service", return_value=AsyncMock()),
        ):
            view = await get_tenant(tenant_id, admin)
            assert view.whatsapp_config.phone_number_id == "843210"
            assert view.whatsapp_config.business_account_id == "fixture-biz"
            assert "synthetic-before" not in repr(view.model_dump())
            changed = dict(config, access_token="synthetic-after")
            response = await update_tenant(tenant_id, TenantUpdate(whatsapp_config=changed), admin)
            assert "synthetic-after" not in repr(response.model_dump())
            context = await TenantResolver.from_tenant_id_header(str(tenant_id))
            assert context.whatsapp_config["access_token"] == "synthetic-after"
            await update_template("status_update", NotificationTemplateUpdate(template_name="fixture_template"), context, admin)
        async with engine.connect() as conn:
            stored = await conn.scalar(text("SELECT whatsapp_config FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        assert "synthetic-after" not in repr(stored) and "fixture_template" not in repr(stored)
        opened = await open_channel_config(tenant_id, stored, cipher)
        assert opened["access_token"] == "synthetic-after"
        assert opened["notification_templates"]["status_update"] == "fixture_template"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()
