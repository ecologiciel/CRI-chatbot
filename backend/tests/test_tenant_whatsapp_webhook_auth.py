"""Security invariants for institution-specific Meta webhook credentials."""

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

from app.core.exceptions import WhatsAppSignatureError
from app.core.tenant import TenantContext, TenantResolver
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import seal_channel_config
from app.services.whatsapp.inbox_intake import persist_tenant_authenticated_webhook
from app.services.whatsapp.tenant_webhook_auth import (
    TenantWebhookPayloadError,
    authenticate_tenant_payload,
    verify_tenant_challenge,
)


def tenant(phone: str, secret: str, token: str) -> TenantContext:
    return TenantContext(uuid.uuid4(), "fixture", "Fixture", "active", {
        "phone_number_id": phone, "app_secret": secret, "verify_token": token,
    })


def body(*phones: str) -> bytes:
    return json.dumps({"object": "whatsapp_business_account", "entry": [{
        "id": "fixture-account", "changes": [{
            "field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "fixture", "phone_number_id": phone},
                "messages": [{"id": "fixture-message", "from": "212600000000", "timestamp": "1", "type": "text", "text": {"body": "hello"}}],
            },
        } for phone in phones],
    }]}).encode()


def signature(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_challenge_is_bound_to_each_tenant_and_never_returns_credentials():
    first = tenant("111", "first-secret", "first-token")
    second = tenant("222", "second-secret", "second-token")
    assert verify_tenant_challenge(first, "subscribe", "first-token", "challenge") == "challenge"
    with pytest.raises(WhatsAppSignatureError):
        verify_tenant_challenge(second, "subscribe", "first-token", "challenge")
    for mode, token in (("unsubscribe", "first-token"), ("subscribe", ""), ("subscribe", "autre")):
        with pytest.raises(WhatsAppSignatureError) as error:
            verify_tenant_challenge(first, mode, token, "challenge")
        assert "first-token" not in str(error.value)


def test_signature_and_every_change_are_bound_to_one_tenant():
    first = tenant("111", "first-secret", "first-token")
    second = tenant("222", "second-secret", "second-token")
    raw = body("111")
    assert authenticate_tenant_payload(first, raw, signature(raw, "first-secret")).entry
    with pytest.raises(WhatsAppSignatureError):
        authenticate_tenant_payload(second, raw, signature(raw, "first-secret"))
    with pytest.raises(TenantWebhookPayloadError):
        authenticate_tenant_payload(second, raw, signature(raw, "second-secret"))
    mixed = body("111", "222")
    with pytest.raises(TenantWebhookPayloadError):
        authenticate_tenant_payload(first, mixed, signature(mixed, "first-secret"))
    with pytest.raises(WhatsAppSignatureError):
        authenticate_tenant_payload(first, raw + b" ", signature(raw, "first-secret"))


@pytest.mark.parametrize("bad", [None, "", "sha256=wrong", "sha256=" + "g" * 64, "sha256=" + "a" * 64 + "\n"])
def test_invalid_signatures_fail_closed(bad):
    with pytest.raises(WhatsAppSignatureError):
        authenticate_tenant_payload(tenant("111", "first-secret", "first-token"), body("111"), bad)


def test_missing_credentials_and_invalid_or_empty_payloads_fail_closed():
    missing = tenant("111", "", "")
    with pytest.raises(WhatsAppSignatureError):
        verify_tenant_challenge(missing, "subscribe", "token", "challenge")
    with pytest.raises(WhatsAppSignatureError):
        verify_tenant_challenge(tenant("111", "", "token"), "subscribe", "token", "challenge")
    with pytest.raises(WhatsAppSignatureError):
        authenticate_tenant_payload(missing, body("111"), "sha256=" + "a" * 64)
    valid = tenant("111", "fixture-secret", "fixture-token")
    for raw in (b"not-json", body()):
        with pytest.raises(TenantWebhookPayloadError):
            authenticate_tenant_payload(valid, raw, signature(raw, "fixture-secret"))


@pytest.mark.asyncio
async def test_durable_intake_validates_entire_batch_before_any_write():
    first = tenant("111", "first-secret", "first-token")
    inbox, statuses = AsyncMock(return_value=True), AsyncMock(return_value=True)
    with (
        patch("app.services.whatsapp.inbox_intake.get_settings", return_value=SimpleNamespace(kms_master_key="00" * 32)),
        patch("app.services.whatsapp.inbox_intake.get_session_factory", return_value=None),
        patch("app.services.whatsapp.inbox_intake.persist_incoming_message", inbox),
        patch("app.services.whatsapp.inbox_intake.persist_delivery_status", statuses),
    ):
        mixed = body("111", "222")
        with pytest.raises(TenantWebhookPayloadError):
            await persist_tenant_authenticated_webhook(first, mixed, signature(mixed, "first-secret"))
        inbox.assert_not_awaited()
        statuses.assert_not_awaited()
        raw = body("111")
        await persist_tenant_authenticated_webhook(first, raw, signature(raw, "first-secret"))
        assert inbox.await_count == 1
        assert inbox.await_args.kwargs["require_current_signing_secret"] is True


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_KMS_DB_URL"), reason="requires disposable PostgreSQL")
async def test_encrypted_tenant_credentials_stay_isolated_in_postgresql():
    engine = create_async_engine(os.environ["TEST_KMS_DB_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = [uuid.uuid4(), uuid.uuid4()]
    master = secrets.token_hex(32)
    settings = SimpleNamespace(kms_master_key=master, whatsapp_config_require_encryption=True)
    kms = KMSService(factory, AsyncMock(), master)
    cipher = VersionedEnvelopeService(factory, master)
    configs = [
        {"phone_number_id": "87812001", "app_secret": "synthetic-first-secret", "verify_token": "synthetic-first-token", "access_token": "first-access"},
        {"phone_number_id": "87812002", "app_secret": "synthetic-second-secret", "verify_token": "synthetic-second-token", "access_token": "second-access"},
    ]
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            for tenant_id in ids:
                await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"), {"id": tenant_id, "slug": "wasig" + tenant_id.hex})
        for tenant_id, config in zip(ids, configs, strict=True):
            await kms.generate_tenant_key(tenant_id)
            stored = await seal_channel_config(tenant_id, config, cipher)
            assert "synthetic-" not in json.dumps(stored)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:value AS jsonb) WHERE id=:id"), {"id": tenant_id, "value": json.dumps(stored)})
        with (
            patch("app.core.config.get_settings", return_value=settings),
            patch("app.core.tenant.get_session_factory", return_value=factory),
        ):
            first, second = [await TenantResolver.from_tenant_id_header(str(value)) for value in ids]
            raw = body(configs[0]["phone_number_id"])
            assert authenticate_tenant_payload(first, raw, signature(raw, configs[0]["app_secret"]))
            assert verify_tenant_challenge(first, "subscribe", configs[0]["verify_token"], "ok") == "ok"
            with pytest.raises(WhatsAppSignatureError):
                authenticate_tenant_payload(second, raw, signature(raw, configs[0]["app_secret"]))
            with pytest.raises(TenantWebhookPayloadError):
                authenticate_tenant_payload(second, raw, signature(raw, configs[1]["app_secret"]))
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id IN (:a,:b)"), {"a": ids[0], "b": ids[1]})
        await engine.dispose()
