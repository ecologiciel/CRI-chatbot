"""The tenant-specific route is gated and never acknowledges uncommitted events."""

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.tenant import TenantContext
from app.main import app
from app.schemas.tenant import WhatsAppConfig


def fixture_tenant(phone, secret, token):
    return TenantContext(uuid.uuid4(), "fixture", "Fixture", "active", {
        "phone_number_id": phone, "access_token": "fixture-access",
        "app_secret": secret, "verify_token": token,
    })


def payload(*phones):
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "fixture", "changes": [
        {"field": "messages", "value": {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "fixture", "phone_number_id": phone},
         "messages": [{"id": "fixture-message", "from": "212600000000", "timestamp": "1", "type": "text", "text": {"body": "fixture"}}],
         "statuses": [{"id": "fixture-status", "status": "delivered", "timestamp": "1", "recipient_id": "212600000000"}]}}
        for phone in phones]}]}).encode()


def sign(raw, secret):
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


@pytest.fixture
def harness():
    settings = SimpleNamespace(
        whatsapp_tenant_webhook_enabled=True, whatsapp_durable_inbox_enabled=True,
        webhook_proxy_shared_secret="", whatsapp_webhook_max_body_bytes=4096,
        kms_master_key="01" * 32,
    )
    first = fixture_tenant("111", "fixture-first-secret", "fixture-first-token")
    second = fixture_tenant("222", "fixture-second-secret", "fixture-second-token")
    resolver = AsyncMock(side_effect=lambda slug: {"one": first, "two": second}[slug])
    redis = SimpleNamespace(exists=AsyncMock(return_value=1))
    inbox, statuses = AsyncMock(return_value=True), AsyncMock(return_value=True)
    with (
        patch("app.api.v1.webhook.get_settings", return_value=settings),
        patch("app.api.v1.webhook.get_redis", return_value=redis),
        patch("app.api.v1.webhook.TenantResolver.from_slug", resolver),
        patch("app.services.whatsapp.inbox_intake.get_settings", return_value=settings),
        patch("app.services.whatsapp.inbox_intake.get_session_factory", return_value=None),
        patch("app.services.whatsapp.inbox_intake.persist_incoming_message", inbox),
        patch("app.services.whatsapp.inbox_intake.persist_delivery_status", statuses),
    ):
        yield settings, resolver, redis, inbox, statuses


@pytest.mark.asyncio
async def test_disabled_and_unavailable_worker_never_accept(harness):
    settings, resolver, redis, inbox, _ = harness
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        settings.whatsapp_tenant_webhook_enabled = False
        assert (await client.post("/api/v1/webhook/whatsapp/tenant/one", content=b"x")).status_code == 404
        settings.whatsapp_tenant_webhook_enabled = True
        settings.whatsapp_durable_inbox_enabled = False
        assert (await client.post("/api/v1/webhook/whatsapp/tenant/one", content=b"x")).status_code == 503
        settings.whatsapp_durable_inbox_enabled = True
        redis.exists.return_value = 0
        assert (await client.post("/api/v1/webhook/whatsapp/tenant/one", content=b"x")).status_code == 503
    resolver.assert_not_awaited()
    inbox.assert_not_awaited()


@pytest.mark.asyncio
async def test_challenge_is_scoped_and_does_not_reflect_bad_token(harness):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        params = {"hub.mode": "subscribe", "hub.verify_token": "fixture-first-token", "hub.challenge": "fixture-challenge"}
        valid = await client.get("/api/v1/webhook/whatsapp/tenant/one", params=params)
        assert valid.status_code == 200 and valid.text == "fixture-challenge"
        wrong = await client.get("/api/v1/webhook/whatsapp/tenant/two", params=params)
        assert wrong.status_code == 403 and "fixture-first-token" not in wrong.text
        duplicate = await client.get("/api/v1/webhook/whatsapp/tenant/one", params=[*params.items(), ("hub.verify_token", "another")])
        assert duplicate.status_code == 403 and "fixture-first-token" not in duplicate.text


@pytest.mark.asyncio
async def test_configured_relay_secret_is_required(harness):
    settings, _, _, _, _ = harness
    settings.webhook_proxy_shared_secret = "fixture-relay-secret"
    params = {"hub.mode": "subscribe", "hub.verify_token": "fixture-first-token", "hub.challenge": "ok"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/webhook/whatsapp/tenant/one", params=params)).status_code == 403
        assert (await client.get("/api/v1/webhook/whatsapp/tenant/one", params=params, headers=[(b"x-demo-webhook-proxy", b"\xff")])).status_code == 403
        assert (await client.get("/api/v1/webhook/whatsapp/tenant/one", params=params, headers={"x-demo-webhook-proxy": "fixture-relay-secret"})).status_code == 200


@pytest.mark.asyncio
async def test_cross_tenant_forgery_and_mixed_batches_never_write(harness):
    _, _, _, inbox, statuses = harness
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        raw = payload("111")
        wrong = await client.post("/api/v1/webhook/whatsapp/tenant/two", content=raw, headers={"X-Hub-Signature-256": sign(raw, "fixture-first-secret")})
        assert wrong.status_code == 403
        mixed = payload("111", "222")
        rejected = await client.post("/api/v1/webhook/whatsapp/tenant/one", content=mixed, headers={"X-Hub-Signature-256": sign(mixed, "fixture-first-secret")})
        assert rejected.status_code == 400
    inbox.assert_not_awaited()
    statuses.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_requires_both_event_writes_and_failures_return_503(harness):
    settings, _, _, inbox, statuses = harness
    raw = payload("111")
    headers = {"X-Hub-Signature-256": sign(raw, "fixture-first-secret")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/webhook/whatsapp/tenant/one", content=raw, headers=headers)
        assert response.status_code == 200
        assert inbox.await_args.kwargs["require_current_signing_secret"] is True
        assert statuses.await_args.kwargs["require_current_signing_secret"] is True
        statuses.side_effect = RuntimeError("fixture private internal error")
        response = await client.post("/api/v1/webhook/whatsapp/tenant/one", content=raw, headers=headers)
        assert response.status_code == 503 and "fixture private" not in response.text
        settings.whatsapp_webhook_max_body_bytes = 10
        response = await client.post("/api/v1/webhook/whatsapp/tenant/one", content=raw, headers=headers)
        assert response.status_code == 413


def test_credentials_are_excluded_from_schema_repr():
    config = WhatsAppConfig(phone_number_id="123", access_token="fixture-access", verify_token="fixture-token", app_secret="fixture-secret")
    assert all(value not in repr(config) for value in ("fixture-access", "fixture-token", "fixture-secret"))
