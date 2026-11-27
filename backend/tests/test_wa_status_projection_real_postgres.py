"""Provider status correlation against disposable tenant schemas."""

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.schemas.whatsapp import StatusInfo
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.status_inbox import persist_delivery_status
from app.services.whatsapp.status_projection import apply_status_event

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_status_projection_checks_recipient_and_institution():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ta, tb, contact, conversation, message = (uuid.uuid4() for _ in range(5))
    first = TenantContext(ta, "fixture_status_a", "A", "active", {"phone_number_id": "901"})
    second = TenantContext(tb, "fixture_status_b", "B", "active", {"phone_number_id": "902"})
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("""
            INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config)
            VALUES (:a,'A','fixture_status_a','Test','active','{"phone_number_id":"901"}'),
                   (:b,'B','fixture_status_b','Test','active','{"phone_number_id":"902"}')
        """), {"a": ta, "b": tb})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(first.slug)
        await TenantProvisioningService()._create_schema(second.slug)
    cipher = VersionedEnvelopeService(factory, "04" * 32)
    kms = KMSService(factory, AsyncMock(), "04" * 32)
    await kms.generate_tenant_key(ta)
    await kms.generate_tenant_key(tb)
    statuses = [
        (first, "901", StatusInfo(id="fixture-message", status="delivered", timestamp="1", recipient_id="212600000001")),
        (first, "901", StatusInfo(id="fixture-message", status="read", timestamp="2", recipient_id="212600000002")),
        (second, "902", StatusInfo(id="fixture-message", status="read", timestamp="3", recipient_id="212600000001")),
        (first, "901", StatusInfo(id="fixture-message", status="sent", timestamp="4", recipient_id="212600000001")),
        (first, "901", StatusInfo(id="fixture-message", status="failed", timestamp="5", recipient_id="212600000001")),
    ]
    with (
        patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
        patch("app.core.tenant.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.status_inbox.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.status_projection.get_session_factory", return_value=factory),
    ):
        for tenant, channel, status in statuses:
            assert await persist_delivery_status(tenant, channel, status, cipher=cipher, fingerprint_key=b"a" * 32)
        assert not await persist_delivery_status(first, "901", statuses[0][2], cipher=cipher, fingerprint_key=b"a" * 32)
        async with engine.connect() as conn:
            events = (await conn.execute(text("SELECT id,tenant_id FROM public.whatsapp_status_events WHERE tenant_id IN (:a,:b) ORDER BY created_at,id"), {"a": ta, "b": tb})).all()
        assert len(events) == 5
        first_id, mismatch_id, other_id, stale_id, conflict_id = (row.id for row in events)
        assert await apply_status_event(first_id, cipher=cipher) == "waiting"
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO tenant_fixture_status_a.contacts (id,phone) VALUES (:id,'+212600000001')"), {"id": contact})
            await conn.execute(text("INSERT INTO tenant_fixture_status_a.conversations (id,contact_id) VALUES (:id,:contact)"), {"id": conversation, "contact": contact})
            await conn.execute(text("INSERT INTO tenant_fixture_status_a.messages (id,conversation_id,direction,type,whatsapp_message_id) VALUES (:id,:conversation,'outbound','text','fixture-message')"), {"id": message, "conversation": conversation})
            await conn.execute(text("UPDATE public.whatsapp_status_events SET next_attempt_at=now() WHERE id=:id"), {"id": first_id})
        assert await apply_status_event(first_id, cipher=cipher) == "applied"
        assert await apply_status_event(first_id, cipher=cipher) == "applied"
        assert await apply_status_event(mismatch_id, cipher=cipher) == "uncertain"
        assert await apply_status_event(other_id, cipher=cipher) == "waiting"
        assert await apply_status_event(stale_id, cipher=cipher) == "applied"
        assert await apply_status_event(conflict_id, cipher=cipher) == "uncertain"
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT metadata->>'delivery_state' FROM tenant_fixture_status_a.messages WHERE id=:id"), {"id": message})) == "delivered"
            assert (await conn.scalar(text("SELECT metadata->>'delivery_review_required' FROM tenant_fixture_status_a.messages WHERE id=:id"), {"id": message})) == "true"
    await engine.dispose()
