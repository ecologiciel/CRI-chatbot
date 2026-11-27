"""STOP/send fencing with synthetic provider calls and disposable PostgreSQL."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.schemas.whatsapp import IncomingMessage
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.inbox import persist_incoming_message
from app.services.whatsapp.inbox_leases import claim_next, finish_claim
from app.services.whatsapp.outbound_fence import OutboundFenceError, OutboundSuperseded, outbound_scope
from app.services.whatsapp.sender import WhatsAppSenderService

URL = os.getenv("TEST_WA_FENCE_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_stop_serializes_with_provider_request_and_suppresses_later_sends():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    phone = "212600000005"
    tenant = TenantContext(tenant_id, "fixture_fence", "Fixture", "active", {"phone_number_id": "987", "access_token": "synthetic"})
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_fence','Test','active',CAST(:cfg AS jsonb))"), {"id": tenant_id, "cfg": '{"phone_number_id":"987"}'})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema("fixture_fence")
    kms = KMSService(factory, AsyncMock(), "03" * 32)
    cipher = VersionedEnvelopeService(factory, "03" * 32)
    await kms.generate_tenant_key(tenant_id)
    first = IncomingMessage.model_validate({"id": "first", "from": phone, "timestamp": "1", "type": "text", "text": {"body": "question"}})
    stop = IncomingMessage.model_validate({"id": "stop", "from": phone, "timestamp": "2", "type": "text", "text": {"body": "STOP"}})
    started, release = asyncio.Event(), asyncio.Event()
    response = MagicMock()
    response.json.return_value = {"messages": [{"id": "synthetic-provider-id"}]}
    client = AsyncMock()
    client.__aenter__.return_value = client

    async def provider_call(*_args, **_kwargs):
        started.set()
        await release.wait()
        return response

    client.post.side_effect = provider_call
    with (
        patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
        patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.outbound_fence.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=client),
    ):
        assert await persist_incoming_message(tenant, "987", first, [], cipher=cipher)
        claim = await claim_next()
        assert claim is not None
        sender = WhatsAppSenderService()
        with outbound_scope(claim, phone) as scope:
            with pytest.raises(OutboundFenceError):
                await sender.send_text(tenant, "different-recipient", "fixture")
            client.post.assert_not_awaited()
            sending = asyncio.create_task(sender.send_text(tenant, phone, "fixture"))
            await asyncio.wait_for(started.wait(), timeout=10)
            stopping = asyncio.create_task(persist_incoming_message(tenant, "987", stop, [], cipher=cipher))
            blocked = False
            try:
                for _ in range(50):
                    async with engine.connect() as monitor:
                        blocked = (await monitor.execute(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%pg_advisory_xact_lock%')"))).scalar_one()
                    if blocked or stopping.done():
                        break
                    await asyncio.sleep(0.1)
                assert blocked and not stopping.done()
            finally:
                release.set()
            assert await asyncio.wait_for(sending, timeout=10) == "synthetic-provider-id"
            assert await asyncio.wait_for(stopping, timeout=10)
            async with engine.begin() as conn:
                assert (await conn.execute(text("SELECT opt_in_status::text FROM tenant_fixture_fence.contacts WHERE phone=:phone"), {"phone": phone})).scalar_one() == "opted_out"
                await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_suppression CHECK (action <> 'wa_send_suppressed') NOT VALID"))
            try:
                with outbound_scope(claim, phone) as failed_scope, pytest.raises(DBAPIError):
                    await sender.send_text(tenant, phone, "must-not-send")
                assert not failed_scope.suppressed
                assert client.post.await_count == 1
            finally:
                async with engine.begin() as conn:
                    await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_suppression"))
            with pytest.raises(OutboundSuperseded):
                await sender.send_text(tenant, phone, "must-not-send")
            with pytest.raises(OutboundSuperseded):
                await sender.send_text(tenant, phone, "still-must-not-send")
            assert scope.suppressed and client.post.await_count == 1
            async with engine.connect() as conn:
                assert (await conn.execute(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug='fixture_fence' AND action='wa_send_suppressed'"))).scalar_one() == 1
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
        with outbound_scope(claim, phone), pytest.raises(OutboundFenceError):
            await sender.send_text(tenant, phone, "claim-already-finished")
        assert client.post.await_count == 1
    await engine.dispose()
