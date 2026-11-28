"""Staged channel-envelope and key-rotation checks on disposable PostgreSQL."""

import asyncio
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.notifications import update_template
from app.api.v1.tenant import get_tenant, update_tenant, update_whatsapp_channel
from app.core.exceptions import (
    CRIDecryptionError,
    CRIEncryptionError,
    DuplicateResourceError,
    TenantProvisioningError,
)
from app.core.tenant import TenantResolver
from app.schemas.notification import NotificationTemplateUpdate
from app.schemas.tenant import TenantCreate, TenantUpdate, WhatsAppChannelUpdate
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.config_envelope import open_channel_config, seal_channel_config
from app.services.whatsapp.config_startup_guard import verify_channel_configs_on_startup

URL = os.getenv("TEST_KMS_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_channel_update_preserves_settings_and_audits_atomically():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    slug = "waupdate" + tenant_id.hex
    master = secrets.token_hex(32)
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    cipher = VersionedEnvelopeService(factory, master)
    original = {"phone_number_id": "873456789", "access_token": "old-access", "verify_token": "old-verify", "notification_templates": {"status": "keep"}, "annual_message_limit": 1234}
    change = WhatsAppChannelUpdate(phone_number_id="873456789", business_account_id="87654", access_token="new-access-secret", verify_token="new-verify-secret", app_secret="new-app-secret")
    admin = MagicMock(sub=str(uuid.uuid4()))
    constraint = False
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"), {"id": tenant_id, "slug": slug})
        await KMSService(factory, AsyncMock(), master).generate_tenant_key(tenant_id)
        sealed = await seal_channel_config(tenant_id, original, cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:value AS jsonb) WHERE id=:id"), {"id": tenant_id, "value": json.dumps(sealed)})
        with (
            patch("app.api.v1.tenant.get_settings", return_value=settings),
            patch("app.api.v1.tenant.get_session_factory", return_value=factory),
        ):
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_wa_channel_update CHECK (action <> 'wa_channel_update') NOT VALID"))
                constraint = True
            with pytest.raises(IntegrityError):
                await update_whatsapp_channel(tenant_id, change, admin)
            async with engine.begin() as conn:
                stored = await conn.scalar(text("SELECT whatsapp_config FROM public.tenants WHERE id=:id"), {"id": tenant_id})
                assert stored == sealed
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_wa_channel_update"))
                constraint = False
            result = await update_whatsapp_channel(tenant_id, change, admin)
        assert result.phone_number_id == change.phone_number_id
        assert "secret" not in repr(result.model_dump())
        async with engine.connect() as conn:
            stored = await conn.scalar(text("SELECT whatsapp_config FROM public.tenants WHERE id=:id"), {"id": tenant_id})
            audit = await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug=:slug AND action='wa_channel_update'"), {"slug": slug})
        assert "new-access-secret" not in json.dumps(stored) and "new-app-secret" not in json.dumps(stored)
        decoded = await open_channel_config(tenant_id, stored, cipher)
        assert decoded["notification_templates"] == {"status": "keep"}
        assert decoded["annual_message_limit"] == 1234 and decoded["app_secret"] == "new-app-secret"
        assert audit == 1
    finally:
        async with engine.begin() as conn:
            if constraint:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_wa_channel_update"))
            await conn.execute(text("DELETE FROM public.audit_logs WHERE tenant_slug=:slug AND action='wa_channel_update'"), {"slug": slug})
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_strict_startup_rejects_plaintext_and_tampered_channels():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    slug = "wastart" + tenant_id.hex
    master = secrets.token_hex(32)
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    config = {"phone_number_id": "12345678901", "access_token": "fixture-secret"}
    cipher = VersionedEnvelopeService(factory, master)
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture',:slug,'Test','active',CAST(:config AS jsonb))"), {"id": tenant_id, "slug": slug, "config": json.dumps(config)})
        with (
            patch("app.services.whatsapp.config_startup_guard.get_settings", return_value=settings),
            patch("app.services.whatsapp.config_startup_guard.get_session_factory", return_value=factory),
            patch("app.core.config.get_settings", return_value=settings),
            patch("app.core.tenant.get_session_factory", return_value=factory),
        ):
            with pytest.raises(RuntimeError, match="Channel configuration validation failed"):
                await verify_channel_configs_on_startup()
            await KMSService(factory, AsyncMock(), master).generate_tenant_key(tenant_id)
            sealed = await seal_channel_config(tenant_id, config, cipher)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"id": tenant_id, "config": json.dumps(sealed)})
            await verify_channel_configs_on_startup()
            altered = dict(sealed, phone_number_id="999999")
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"id": tenant_id, "config": json.dumps(altered)})
            with pytest.raises(RuntimeError, match="Channel configuration validation failed"):
                await verify_channel_configs_on_startup()
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()


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


@pytest.mark.asyncio
async def test_strict_provisioning_never_commits_plaintext_and_preserves_key_after_failure():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:20]
    slug, failed_slug, aborted_slug = "waok" + suffix, "wafail" + suffix, "waabort" + suffix
    race_a, race_b = "waracea" + suffix, "waraceb" + suffix
    master = secrets.token_hex(32)
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    cipher = VersionedEnvelopeService(factory, master)
    phone_base = str(700000000000 + int(suffix[:8], 16))

    def create_data(name, phone):
        return TenantCreate(
            name="Fixture", slug=name, region="Test",
            whatsapp_config={"phone_number_id": phone, "access_token": "synthetic-provision-secret", "verify_token": "synthetic-verifier"},
        )

    @asynccontextmanager
    async def unlocked(_slug):
        yield

    try:
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        service = TenantProvisioningService()
        service._create_schema = AsyncMock()
        service._drop_schema = AsyncMock()
        service._create_qdrant_collection = AsyncMock()
        service._create_redis_mapping = AsyncMock()
        service._create_minio_bucket = AsyncMock()
        with (
            patch("app.services.tenant.provisioning.get_session_factory", return_value=factory),
            patch("app.services.tenant.provisioning.get_settings", return_value=settings),
            patch("app.services.tenant.provisioning.protect_removal", unlocked),
        ):
            with patch("app.services.tenant.provisioning.seal_channel_config", new=AsyncMock(side_effect=RuntimeError("fixture failure"))):
                with pytest.raises(RuntimeError):
                    await service._create_tenant_record(create_data(aborted_slug, phone_base + "1"))
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT count(*) FROM public.tenants WHERE slug=:slug"), {"slug": aborted_slug})) == 0
            results = await asyncio.gather(
                service._create_tenant_record(create_data(race_a, phone_base + "4")),
                service._create_tenant_record(create_data(race_b, phone_base + "4")),
                return_exceptions=True,
            )
            assert sum(isinstance(result, DuplicateResourceError) for result in results) == 1
            assert sum(not isinstance(result, BaseException) for result in results) == 1
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT count(*) FROM public.tenants WHERE slug IN (:a,:b)"), {"a": race_a, "b": race_b})) == 1
            tenant = await service.provision_tenant(create_data(slug, phone_base + "2"))
            assert tenant.status.value == "active"
            assert "synthetic-provision-secret" not in repr(tenant.whatsapp_config)
            assert (await open_channel_config(tenant.id, tenant.whatsapp_config, cipher))["access_token"] == "synthetic-provision-secret"
            service._create_qdrant_collection.side_effect = RuntimeError("fixture failure")
            with pytest.raises(TenantProvisioningError):
                await service.provision_tenant(create_data(failed_slug, phone_base + "3"))
        async with engine.connect() as conn:
            failed = (await conn.execute(text("SELECT id,status::text,whatsapp_config FROM public.tenants WHERE slug=:slug"), {"slug": failed_slug})).one()
            assert failed.status == "inactive"
            assert "synthetic-provision-secret" not in repr(failed.whatsapp_config)
            assert (await conn.scalar(text("SELECT count(*) FROM public.tenant_keys WHERE tenant_id=:id"), {"id": failed.id})) == 1
        assert (await open_channel_config(failed.id, failed.whatsapp_config, cipher))["access_token"] == "synthetic-provision-secret"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE slug IN (:a,:b,:c,:d,:e)"), {"a": slug, "b": failed_slug, "c": aborted_slug, "d": race_a, "e": race_b})
        await engine.dispose()
