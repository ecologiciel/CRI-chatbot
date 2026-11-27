"""Idempotent, encrypted reply registration on disposable PostgreSQL."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation.reply_leases import (
    AgentReplyClaim,
    AgentReplyLeaseLostError,
    claim_next_reply,
    finish_reply,
    quarantine_expired_replies,
)
from app.services.escalation.reply_outbox import AgentReplyConflictError, register_agent_reply
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_reply_registration_is_idempotent_scoped_and_audited():
    # More concurrent requests than connections must not deadlock while
    # holding lifecycle locks and waiting for encryption keys.
    engine = create_async_engine(URL, pool_size=4, max_overflow=0, pool_timeout=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ta, tb, aa, ab, ac, ca, cb, va, vb, ea, eb, request = (uuid.uuid4() for _ in range(12))
    a = TenantContext(ta, "fixture_reply_a", "A", "active", None)
    b = TenantContext(tb, "fixture_reply_b", "B", "active", None)
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("""
            INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config)
            VALUES (:a,'A','fixture_reply_a','Test','active','{"phone_number_id":"971","access_token":"fixture"}'),
                   (:b,'B','fixture_reply_b','Test','active','{"phone_number_id":"972","access_token":"fixture"}')
        """), {"a": ta, "b": tb})
        await conn.execute(text("""
            INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id)
            VALUES (:a,'reply-a@example.test','fixture','A','admin_tenant',:ta),
                   (:b,'reply-b@example.test','fixture','B','supervisor',:tb),
                   (:c,'reply-c@example.test','fixture','C','supervisor',:ta)
        """), {"a": aa, "b": ab, "c": ac, "ta": ta, "tb": tb})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(a.slug)
        await TenantProvisioningService()._create_schema(b.slug)
    for schema, contact, conversation, escalation in (
        ("tenant_fixture_reply_a", ca, va, ea), ("tenant_fixture_reply_b", cb, vb, eb)
    ):
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO {schema}.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000099','opted_in')"), {"id": contact})
            await conn.execute(text(f"INSERT INTO {schema}.conversations (id,contact_id,status) VALUES (:id,:contact,'human_handled')"), {"id": conversation, "contact": contact})
            await conn.execute(text(f"INSERT INTO {schema}.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','assigned')"), {"id": escalation, "conversation": conversation})
    cipher = VersionedEnvelopeService(factory, "05" * 32)
    kms = KMSService(factory, AsyncMock(), "05" * 32)
    await kms.generate_tenant_key(ta)
    await kms.generate_tenant_key(tb)
    with (patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
          patch("app.services.escalation.reply_outbox.get_session_factory", return_value=factory)):
        results = await asyncio.gather(*(
            register_agent_reply(a, ea, aa, request, "fixture-private-text", cipher=cipher)
            for _ in range(12)
        ))
        assert len({result.id for result in results}) == 1
        assert sum(result.created for result in results) == 1
        assert all(result.state == "pending" for result in results)
        first = results[0].id
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT ciphertext,recipient_fingerprint,state FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": first})).one()
            assert "fixture-private-text" not in row.ciphertext and "212600000099" not in row.recipient_fingerprint
            assert row.state == "pending"
            assert (await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug='fixture_reply_a' AND action='agent_reply_queued'"))) == 1
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(a, ea, aa, request, "changed private text", cipher=cipher)
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(a, ea, ab, request, "fixture-private-text", cipher=cipher)
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(a, ea, ac, request, "fixture-private-text", cipher=cipher)
        other = await register_agent_reply(b, eb, ab, request, "fixture-private-text", cipher=cipher)
        assert other.created and other.id != first
        await kms.rotate_key(ta, a.slug)
        assert (await register_agent_reply(a, ea, aa, request, "fixture-private-text", cipher=cipher)).id == first
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_reply_a.escalations SET status='resolved' WHERE id=:id"), {"id": ea})
        assert not (await register_agent_reply(a, ea, aa, request, "fixture-private-text", cipher=cipher)).created
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(a, ea, aa, uuid.uuid4(), "another", cipher=cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_reply_a.escalations SET status='assigned' WHERE id=:id"), {"id": ea})
            await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_agent_reply CHECK (action <> 'agent_reply_queued') NOT VALID"))
        failed = uuid.uuid4()
        try:
            with pytest.raises(DBAPIError):
                await register_agent_reply(a, ea, aa, failed, "fixture", cipher=cipher)
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT count(*) FROM public.agent_reply_outbox_events WHERE tenant_id=:tenant AND request_key=:key"), {"tenant": ta, "key": failed})) == 0
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_agent_reply"))
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_reply_a.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": ca})
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(a, ea, aa, uuid.uuid4(), "fixture", cipher=cipher)
    await engine.dispose()


@pytest.mark.asyncio
async def test_claims_keep_conversation_order_and_quarantine_expiry():
    engine = create_async_engine(URL, pool_size=12)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ta, tb, conversation, other = (uuid.uuid4() for _ in range(4))
    a1, a2, b1, c1 = (uuid.uuid4() for _ in range(4))
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A','fixture_lease_a','Test','active'),(:b,'B','fixture_lease_b','Test','active')"), {"a": ta, "b": tb})
        for event_id, tenant_id, conversation_id in ((a1, ta, conversation), (a2, ta, conversation), (b1, ta, other), (c1, tb, conversation)):
            await conn.execute(text("""
                INSERT INTO public.agent_reply_outbox_events
                  (id,tenant_id,request_key,actor_id,escalation_id,conversation_id,contact_id,
                   phone_number_id,recipient_fingerprint,ciphertext,key_version)
                VALUES (:id,:tenant,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),:conversation,
                        gen_random_uuid(),'123',repeat('a',64),'fixture',1)
            """), {"id": event_id, "tenant": tenant_id, "conversation": conversation_id})

    async def claim():
        async with factory() as session:
            item = await claim_next_reply(session)
            await session.commit()
            return item

    claims = [claim for claim in await asyncio.gather(*(claim() for _ in range(12))) if claim]
    assert {claim.id for claim in claims} == {a1, b1, c1}
    async with factory() as session:
        for item in claims:
            await finish_reply(session, item, provider_message_id=None if item.id == a1 else f"fixture-{item.id}")
        await session.commit()
    assert await claim() is None
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='resolved' WHERE id=:id"), {"id": a1})
    second = await claim()
    assert second and second.id == a2
    async with factory() as session:
        with pytest.raises(AgentReplyLeaseLostError):
            await finish_reply(session, AgentReplyClaim(second.id, second.tenant_id, uuid.uuid4()), provider_message_id="fixture")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE public.agent_reply_outbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": a2})
    async with factory() as session:
        with pytest.raises(AgentReplyLeaseLostError):
            await finish_reply(session, second, provider_message_id="fixture")
    async with factory() as session:
        assert await quarantine_expired_replies(session) == 1
        await session.commit()
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='pending' WHERE id=:id"), {"id": a2})
    assert await claim() is None
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT state,attempts FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": a2})).one()
        assert row.state == "uncertain" and row.attempts == 1
    await engine.dispose()
