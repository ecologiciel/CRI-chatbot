"""Tenant-signed durable intake against a disposable migrated database."""

import hashlib
import hmac
import json
import os
import secrets
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import TenantInactiveError, WhatsAppSignatureError
from app.core.tenant import TenantResolver
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import seal_channel_config
from app.services.whatsapp.inbox_intake import persist_tenant_authenticated_webhook

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


def event(phone, message_id, status_id=None):
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "fixture", "phone_number_id": phone},
             "messages": [{"id": message_id, "from": "212600000000", "timestamp": "1", "type": "text", "text": {"body": "synthetic-private-message"}}]}
    if status_id:
        value["statuses"] = [{"id": status_id, "status": "delivered", "timestamp": "1", "recipient_id": "212600000000"}]
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "account", "changes": [{"field": "messages", "value": value}]}]}).encode()


def sign(raw, key):
    return "sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_encrypted_tenant_intake_commits_deduplicates_and_rejects_rotated_secret():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    master = secrets.token_hex(32)
    config = {"phone_number_id": "87900001", "app_secret": "fixture-signing-key", "verify_token": "fixture-verify", "access_token": "fixture-access"}
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    kms = KMSService(factory, AsyncMock(), master)
    cipher = VersionedEnvelopeService(factory, master)
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"), {"id": tenant_id, "slug": "watest" + tenant_id.hex})
        await kms.generate_tenant_key(tenant_id)
        sealed = await seal_channel_config(tenant_id, config, cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:cfg AS jsonb) WHERE id=:id"), {"id": tenant_id, "cfg": json.dumps(sealed)})
        with (
            patch("app.core.config.get_settings", return_value=settings),
            patch("app.core.tenant.get_session_factory", return_value=factory),
            patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
            patch("app.services.whatsapp.inbox_intake.get_settings", return_value=settings),
            patch("app.services.whatsapp.inbox_intake.get_session_factory", return_value=factory),
            patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
            patch("app.services.whatsapp.status_inbox.get_session_factory", return_value=factory),
        ):
            tenant = await TenantResolver.from_tenant_id_header(str(tenant_id))
            raw = event(config["phone_number_id"], "fixture-1", "fixture-status-1")
            with pytest.raises(WhatsAppSignatureError):
                await persist_tenant_authenticated_webhook(tenant, raw, sign(raw, "wrong"))
            await persist_tenant_authenticated_webhook(tenant, raw, sign(raw, config["app_secret"]))
            await persist_tenant_authenticated_webhook(tenant, raw, sign(raw, config["app_secret"]))
            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT ciphertext FROM public.whatsapp_inbox_events WHERE tenant_id=:id"), {"id": tenant_id})).all()
                status_count = await conn.scalar(text("SELECT count(*) FROM public.whatsapp_status_events WHERE tenant_id=:id"), {"id": tenant_id})
            assert len(row) == 1 and "synthetic-private-message" not in row[0].ciphertext
            assert status_count == 1
            rotated = await seal_channel_config(tenant_id, dict(config, app_secret="fixture-rotated-key"), cipher)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:cfg AS jsonb) WHERE id=:id"), {"id": tenant_id, "cfg": json.dumps(rotated)})
            stale = event(config["phone_number_id"], "fixture-2")
            with pytest.raises(TenantInactiveError):
                await persist_tenant_authenticated_webhook(tenant, stale, sign(stale, config["app_secret"]))
            stale_status = json.loads(event(config["phone_number_id"], "unused", "fixture-status-2"))
            del stale_status["entry"][0]["changes"][0]["value"]["messages"]
            raw_status = json.dumps(stale_status).encode()
            with pytest.raises(TenantInactiveError):
                await persist_tenant_authenticated_webhook(tenant, raw_status, sign(raw_status, config["app_secret"]))
            async with engine.connect() as conn:
                assert await conn.scalar(text("SELECT count(*) FROM public.whatsapp_inbox_events WHERE tenant_id=:id"), {"id": tenant_id}) == 1
                assert await conn.scalar(text("SELECT count(*) FROM public.whatsapp_status_events WHERE tenant_id=:id"), {"id": tenant_id}) == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.whatsapp_status_events WHERE tenant_id=:id"), {"id": tenant_id})
            await conn.execute(text("DELETE FROM public.whatsapp_inbox_events WHERE tenant_id=:id"), {"id": tenant_id})
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()
