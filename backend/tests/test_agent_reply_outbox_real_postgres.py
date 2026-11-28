"""Idempotent, encrypted reply registration on disposable PostgreSQL."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.tenant import TenantContext
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation.reply_execution import AgentReplyPreconditionError, execute_agent_reply
from app.services.escalation.reply_leases import (
    AgentReplyClaim,
    AgentReplyLeaseLostError,
    claim_next_reply,
    quarantine_expired_replies,
    quarantine_reply,
)
from app.services.escalation.reply_outbox import AgentReplyConflictError, register_agent_reply
from app.services.escalation.reply_retention import redact_tenant_replies
from app.services.escalation.reply_review import review_agent_reply
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.config_envelope import seal_channel_config
from app.workers.agent_reply_outbox import process_one_reply

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_retention_redacts_only_terminal_payloads_with_atomic_audit_and_replay_fence():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ta, tb, accepted, resolved, recent, pending, processing, other, request = (uuid.uuid4() for _ in range(9))
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A','fixture_retention_a','Test','active'),(:b,'B','fixture_retention_b','Test','active')"), {"a": ta, "b": tb})
        for event_id, tenant_id, state, old in (
            (accepted, ta, "accepted", True), (resolved, ta, "resolved", True),
            (recent, ta, "accepted", False), (pending, ta, "pending", True),
            (processing, ta, "processing", True), (other, tb, "accepted", True),
        ):
            await conn.execute(text("""
                INSERT INTO public.agent_reply_outbox_events
                  (id,tenant_id,request_key,actor_id,escalation_id,conversation_id,contact_id,
                   phone_number_id,recipient_fingerprint,ciphertext,key_version,state,attempts,
                   provider_message_id,lease_token,lease_until,review_decision,reviewed_by,reviewed_at,updated_at)
                VALUES (:id,:tenant,:key,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
                        '123',repeat('a',64),'synthetic-ciphertext',1,CAST(:state AS text),
                        CASE WHEN CAST(:state AS text) IN ('accepted','processing') THEN 1 ELSE 0 END,
                        CASE WHEN CAST(:state AS text)='accepted' THEN 'synthetic-provider-id' ELSE NULL END,
                        CASE WHEN CAST(:state AS text)='processing' THEN gen_random_uuid() ELSE NULL END,
                        CASE WHEN CAST(:state AS text)='processing' THEN now()+interval '1 hour' ELSE NULL END,
                        CASE WHEN CAST(:state AS text)='resolved' THEN 'unknown_no_retry' ELSE NULL END,
                        CASE WHEN CAST(:state AS text)='resolved' THEN gen_random_uuid() ELSE NULL END,
                        CASE WHEN CAST(:state AS text)='resolved' THEN now() ELSE NULL END,
                        CASE WHEN :old THEN now()-interval '40 days' ELSE now() END)
            """), {"id": event_id, "tenant": tenant_id, "state": state, "old": old,
                     "key": request if event_id == accepted else uuid.uuid4()})
        await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_agent_purge CHECK (action <> 'agent_reply_purge') NOT VALID"))
    with patch("app.services.escalation.reply_retention.get_session_factory", return_value=factory):
        try:
            with pytest.raises(DBAPIError):
                await redact_tenant_replies(ta, "fixture_retention_a", 30, datetime.now(UTC))
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT ciphertext FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": accepted})) == "synthetic-ciphertext"
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_agent_purge"))
        assert await redact_tenant_replies(ta, "fixture_retention_a", 30, datetime.now(UTC)) == {"redacted": 2, "overdue_unresolved": 2}
        assert await redact_tenant_replies(ta, "fixture_retention_a", 30, datetime.now(UTC)) == {"redacted": 0, "overdue_unresolved": 2}
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT state,ciphertext,contact_id,phone_number_id,recipient_fingerprint,provider_message_id,redacted_at FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": accepted})).one()
        assert row.state == "accepted" and row.ciphertext == "" and row.redacted_at is not None
        assert all(value is None for value in (row.contact_id, row.phone_number_id, row.recipient_fingerprint, row.provider_message_id))
        for event_id in (recent, pending, processing, other):
            assert (await conn.scalar(text("SELECT ciphertext FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": event_id})) == "synthetic-ciphertext"
        assert (await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug='fixture_retention_a' AND action='agent_reply_purge'"))) == 1
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET request_key=:key WHERE id=:id"), {"key": request, "id": recent})
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET redacted_at=now(),ciphertext='' WHERE id=:id"), {"id": pending})
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.agent_reply_outbox_events WHERE tenant_id IN (:a,:b)"), {"a": ta, "b": tb})
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("encrypted", [False, True])
async def test_reply_registration_is_idempotent_scoped_and_audited(encrypted):
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
    if encrypted:
        for tenant_id, phone in ((ta, "971"), (tb, "972")):
            sealed = await seal_channel_config(tenant_id, {"phone_number_id": phone, "access_token": "fixture"}, cipher)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST(:config AS jsonb) WHERE id=:id"), {"config": json.dumps(sealed), "id": tenant_id})
    settings = get_settings().model_copy(update={"kms_master_key": "05" * 32})
    with (patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
          patch("app.core.config.get_settings", return_value=settings),
          patch("app.core.tenant.get_session_factory", return_value=factory),
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
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='accepted', attempts=1, provider_message_id='fixture-id' WHERE id=:id"), {"id": first})
        # Separate agents and escalations share the same conversation lock.
        other_escalation = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO tenant_fixture_reply_a.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','assigned')"), {"id": other_escalation, "conversation": va})
        concurrent = await asyncio.gather(
            register_agent_reply(a, ea, aa, uuid.uuid4(), "first-agent", cipher=cipher),
            register_agent_reply(a, other_escalation, ac, uuid.uuid4(), "second-agent", cipher=cipher),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in concurrent) == 1
        assert sum(isinstance(item, AgentReplyConflictError) for item in concurrent) == 1
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='canceled' WHERE tenant_id=:tenant AND state='pending'"), {"tenant": ta})
        async with engine.begin() as conn:
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
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.agent_reply_outbox_events WHERE tenant_id IN (:a,:b)"), {"a": ta, "b": tb})
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
            await quarantine_reply(session, item)
        await session.commit()
    assert await claim() is None
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='resolved', review_decision='unknown_no_retry', reviewed_by=gen_random_uuid(), reviewed_at=now() WHERE id=:id"), {"id": a1})
    second = await claim()
    assert second and second.id == a2
    async with factory() as session:
        with pytest.raises(AgentReplyLeaseLostError):
            await quarantine_reply(session, AgentReplyClaim(second.id, second.tenant_id, uuid.uuid4()))
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE public.agent_reply_outbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": a2})
    async with factory() as session:
        with pytest.raises(AgentReplyLeaseLostError):
            await quarantine_reply(session, second)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_agent_expiry CHECK (action <> 'agent_reply_expired') NOT VALID"))
    try:
        with pytest.raises(DBAPIError):
            async with factory() as session:
                await quarantine_expired_replies(session)
                await session.commit()
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT state FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": a2})) == "processing"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_agent_expiry"))
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


@pytest.mark.asyncio
async def test_one_provider_attempt_respects_stop_and_quarantines_ambiguity():
    engine = create_async_engine(URL, pool_size=12)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, actor_id, contact_id, conversation_id, escalation_id = (uuid.uuid4() for _ in range(5))
    tenant = TenantContext(tenant_id, "fixture_reply_exec", "Fixture", "active", None)
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_reply_exec','Test','active','{\"phone_number_id\":\"973\",\"access_token\":\"fixture\"}')"), {"id": tenant_id})
        await conn.execute(text("INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id) VALUES (:id,'reply-exec@example.test','fixture','Fixture','admin_tenant',:tenant)"), {"id": actor_id, "tenant": tenant_id})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(tenant.slug)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_reply_exec.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000098','opted_in')"), {"id": contact_id})
        await conn.execute(text("INSERT INTO tenant_fixture_reply_exec.conversations (id,contact_id,status) VALUES (:id,:contact,'human_handled')"), {"id": conversation_id, "contact": contact_id})
        await conn.execute(text("INSERT INTO tenant_fixture_reply_exec.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','assigned')"), {"id": escalation_id, "conversation": conversation_id})
    kms = KMSService(factory, AsyncMock(), "06" * 32)
    cipher = VersionedEnvelopeService(factory, "06" * 32)
    await kms.generate_tenant_key(tenant_id)
    sender = AsyncMock()
    started, release = asyncio.Event(), asyncio.Event()

    async def provider_send(*_args, **_kwargs):
        started.set()
        await release.wait()
        return "fixture-provider-id"

    sender.send_text.side_effect = provider_send

    async def claim():
        async with factory() as session:
            item = await claim_next_reply(session)
            await session.commit()
            return item

    with (patch("app.core.tenant.get_session_factory", return_value=factory),
          patch("app.services.escalation.reply_outbox.get_session_factory", return_value=factory),
          patch("app.services.escalation.reply_execution.get_session_factory", return_value=factory)):
        first = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-one", cipher=cipher)
        first_claim = await claim()
        assert first_claim and first_claim.id == first.id
        with pytest.raises(AgentReplyLeaseLostError):
            await execute_agent_reply(AgentReplyClaim(first.id, tenant_id, uuid.uuid4()), cipher=cipher, sender=sender)
        sender.send_text.assert_not_awaited()
        sending = asyncio.create_task(execute_agent_reply(first_claim, cipher=cipher, sender=sender))
        await asyncio.wait_for(started.wait(), timeout=10)
        async with engine.connect() as stopper:
            transaction = await stopper.begin()
            stopper_pid = (await stopper.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            stop = asyncio.create_task(stopper.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": contact_id}))
            blocked = False
            try:
                for _ in range(50):
                    async with engine.connect() as monitor:
                        blocked = await monitor.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": stopper_pid})
                    if blocked or stop.done():
                        break
                    await asyncio.sleep(0.1)
                assert blocked and not stop.done()
            finally:
                release.set()
            assert await asyncio.wait_for(sending, timeout=10) == "accepted"
            await asyncio.wait_for(stop, timeout=10)
            await transaction.commit()
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture", cipher=cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET opt_in_status='opted_in' WHERE id=:id"), {"id": contact_id})
        blocked_reply = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-blocked", cipher=cipher)
        blocked_claim = await claim()
        assert blocked_claim and blocked_claim.id == blocked_reply.id
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": contact_id})
        with pytest.raises(AgentReplyPreconditionError):
            await execute_agent_reply(blocked_claim, cipher=cipher, sender=sender)
        assert sender.send_text.await_count == 1
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": blocked_reply.id})
            await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET opt_in_status='opted_in' WHERE id=:id"), {"id": contact_id})
        async with factory() as session:
            assert await quarantine_expired_replies(session) >= 1
            await session.commit()
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='resolved', review_decision='unknown_no_retry', reviewed_by=gen_random_uuid(), reviewed_at=now() WHERE id=:id"), {"id": blocked_reply.id})
        second = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-two", cipher=cipher)
        second_claim = await claim()
        assert second_claim and second_claim.id == second.id
        sender.send_text.side_effect = RuntimeError("fixture ambiguous provider result")
        assert await execute_agent_reply(second_claim, cipher=cipher, sender=sender) == "uncertain"
        with pytest.raises(AgentReplyConflictError):
            await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-three", cipher=cipher)
        assert await claim() is None
        with patch("app.services.escalation.reply_review.get_session_factory", return_value=factory):
            with pytest.raises(AgentReplyConflictError):
                await review_agent_reply(tenant, uuid.uuid4(), second.id, actor_id, action="follow_up")
            assert await review_agent_reply(tenant, escalation_id, second.id, actor_id, action="follow_up") == "follow_up"
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_agent_review CHECK (action <> 'agent_reply_review') NOT VALID"))
            try:
                with pytest.raises(DBAPIError):
                    await review_agent_reply(tenant, escalation_id, second.id, actor_id, action="resolve", decision="unknown_no_retry")
                async with engine.connect() as conn:
                    assert (await conn.scalar(text("SELECT state FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": second.id})) == "follow_up"
                assert await claim() is None
            finally:
                async with engine.begin() as conn:
                    await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_agent_review"))
            assert await review_agent_reply(tenant, escalation_id, second.id, actor_id, action="resolve", decision="unknown_no_retry") == "resolved"
            with pytest.raises(AgentReplyConflictError):
                await review_agent_reply(tenant, escalation_id, second.id, actor_id, action="resolve", decision="unknown_no_retry")
        third = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-three", cipher=cipher)
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_agent_send CHECK (action <> 'agent_reply_sent') NOT VALID"))
        third_claim = await claim()
        assert third_claim and third_claim.id == third.id
        sender.send_text.side_effect = None
        sender.send_text.return_value = "fixture-third-provider-id"
        try:
            with pytest.raises(DBAPIError):
                await execute_agent_reply(third_claim, cipher=cipher, sender=sender)
            async with engine.begin() as conn:
                assert (await conn.scalar(text("SELECT state FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": third.id})) == "processing"
                assert (await conn.scalar(text("SELECT count(*) FROM tenant_fixture_reply_exec.messages WHERE content='fixture-three'"))) == 0
                await conn.execute(text("UPDATE public.agent_reply_outbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": third.id})
            async with factory() as session:
                assert await quarantine_expired_replies(session) >= 1
                await session.commit()
            assert await claim() is None
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_agent_send"))
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT content,metadata->>'delivery_state' AS state FROM tenant_fixture_reply_exec.messages ORDER BY created_at"))).all()
            assert rows == [("fixture-one", "accepted"), ("fixture-two", "unconfirmed")]
            assert (await conn.scalar(text("SELECT state FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": third.id})) == "uncertain"
        assert sender.send_text.await_count == 3
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='resolved', review_decision='unknown_no_retry', reviewed_by=gen_random_uuid(), reviewed_at=now() WHERE id=:id"), {"id": third.id})
        for scenario in ("actor", "channel", "recipient"):
            event = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), f"fixture-{scenario}", cipher=cipher)
            item = await claim()
            assert item and item.id == event.id
            async with engine.begin() as conn:
                if scenario == "actor":
                    await conn.execute(text("UPDATE public.admins SET is_active=false WHERE id=:id"), {"id": actor_id})
                elif scenario == "channel":
                    await conn.execute(text("UPDATE public.tenants SET whatsapp_config='{\"phone_number_id\":\"974\",\"access_token\":\"fixture\"}' WHERE id=:id"), {"id": tenant_id})
                else:
                    await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET phone='+212600000097' WHERE id=:id"), {"id": contact_id})
            with pytest.raises(AgentReplyPreconditionError):
                await execute_agent_reply(item, cipher=cipher, sender=sender)
            assert sender.send_text.await_count == 3
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.admins SET is_active=true WHERE id=:id"), {"id": actor_id})
                await conn.execute(text("UPDATE public.tenants SET whatsapp_config='{\"phone_number_id\":\"973\",\"access_token\":\"fixture\"}' WHERE id=:id"), {"id": tenant_id})
                await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET phone='+212600000098' WHERE id=:id"), {"id": contact_id})
                await conn.execute(text("UPDATE public.agent_reply_outbox_events SET lease_until=now()-interval '1 second' WHERE id=:id"), {"id": event.id})
            async with factory() as session:
                assert await quarantine_expired_replies(session) >= 1
                await session.commit()
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE public.agent_reply_outbox_events SET state='resolved', review_decision='unknown_no_retry', reviewed_by=gen_random_uuid(), reviewed_at=now() WHERE id=:id"), {"id": event.id})
        queued = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-worker", cipher=cipher)
        worker_sender = AsyncMock()
        worker_sender.send_text.return_value = "fixture-worker-provider-id"
        with (patch("app.workers.agent_reply_outbox.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=True, kms_master_key="06" * 32)),
              patch("app.workers.agent_reply_outbox.get_session_factory", return_value=factory),
              patch("app.workers.agent_reply_outbox.WhatsAppSenderService", return_value=worker_sender)):
            assert await process_one_reply({}) == "accepted"
            assert await process_one_reply({}) == "empty"
            worker_sender.send_text.assert_awaited_once()
            pending = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "fixture-worker-stop", cipher=cipher)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE tenant_fixture_reply_exec.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": contact_id})
            assert await process_one_reply({}) == "uncertain"
            worker_sender.send_text.assert_awaited_once()
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT outcome_code FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": queued.id})) == "provider_accepted"
                assert (await conn.scalar(text("SELECT outcome_code FROM public.agent_reply_outbox_events WHERE id=:id"), {"id": pending.id})) == "precondition_changed"
                assert (await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE action='agent_reply_review' AND resource_id=:id"), {"id": str(pending.id)})) == 1
    await engine.dispose()
