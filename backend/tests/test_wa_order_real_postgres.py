"""Concurrent claiming and blocking rules against a disposable migrated copy."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

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
from app.services.whatsapp.inbox_payload import decrypt_claim
from app.services.whatsapp.inbox_retention import _redact_tenant
from app.services.whatsapp.legacy_reconciliation import (
    LegacyReconciliationError,
    reconcile_legacy_text,
)

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_legacy_stop_reconciliation_is_atomic_and_never_sends():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, event_id, fail_id, actor = (uuid.uuid4() for _ in range(4))
    tenant = TenantContext(tenant_id, "fixture_reconcile", "Fixture", "active", {"phone_number_id": "888"})
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_reconcile','Test','active',CAST(:cfg AS jsonb))"), {"id": tenant_id, "cfg": '{"phone_number_id":"888"}'})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(tenant.slug)
    kms = KMSService(factory, AsyncMock(), "03" * 32)
    cipher = VersionedEnvelopeService(factory, "03" * 32)
    await kms.generate_tenant_key(tenant_id)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_reconcile.contacts (phone,opt_in_status) VALUES ('212600000005','opted_in'),('212600000006','opted_in')"))
    for eid, mid, phone in ((event_id, "legacy-stop-a", "212600000005"), (fail_id, "legacy-stop-b", "212600000006")):
        payload = {"phone_number_id": "888", "message": {"id": mid, "from": phone, "timestamp": "1", "type": "text", "text": {"body": "STOP"}}, "contacts": []}
        envelope = await cipher.encrypt(json.dumps(payload).encode(), tenant_id=tenant_id, purpose="wa_inbox", record_id=eid)
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,state) VALUES (:id,:tenant,:mid,'888',:cipher,:version,'uncertain')"), {"id": eid, "tenant": tenant_id, "mid": mid, "cipher": envelope.ciphertext, "version": envelope.version})
    with (patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
          patch("app.services.whatsapp.legacy_reconciliation.get_session_factory", return_value=factory)):
        assert await reconcile_legacy_text(tenant, event_id, actor, cipher=cipher)
        with pytest.raises(LegacyReconciliationError):
            await reconcile_legacy_text(tenant, event_id, actor, cipher=cipher)
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT opt_in_status::text FROM tenant_fixture_reconcile.contacts WHERE phone='212600000005'"))) == "opted_out"
            row = (await conn.execute(text("SELECT state, sender_fingerprint, is_opt_out FROM public.whatsapp_inbox_events WHERE id=:id"), {"id": event_id})).one()
            assert row.state == "uncertain" and row.sender_fingerprint and row.is_opt_out
            assert (await conn.scalar(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug='fixture_reconcile' AND action='wa_legacy_reconcile'"))) == 1
            await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_legacy CHECK (action <> 'wa_legacy_reconcile') NOT VALID"))
        try:
            with pytest.raises(DBAPIError):
                await reconcile_legacy_text(tenant, fail_id, actor, cipher=cipher)
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT opt_in_status::text FROM tenant_fixture_reconcile.contacts WHERE phone='212600000006'"))) == "opted_in"
                assert (await conn.scalar(text("SELECT sender_fingerprint FROM public.whatsapp_inbox_events WHERE id=:id"), {"id": fail_id})) is None
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_legacy"))
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST('{\"phone_number_id\":\"999\"}' AS jsonb) WHERE id=:id"), {"id": tenant_id})
        with pytest.raises(LegacyReconciliationError):
            await reconcile_legacy_text(tenant, fail_id, actor, cipher=cipher)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.tenants SET whatsapp_config=CAST('{\"phone_number_id\":\"888\"}' AS jsonb) WHERE id=:id"), {"id": tenant_id})
            await conn.execute(text("UPDATE public.whatsapp_inbox_events SET redacted_at=now(), ciphertext='' WHERE id=:id"), {"id": fail_id})
        with pytest.raises(LegacyReconciliationError):
            await reconcile_legacy_text(tenant, fail_id, actor, cipher=cipher)
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT opt_in_status::text FROM tenant_fixture_reconcile.contacts WHERE phone='212600000006'"))) == "opted_in"
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_claims_preserve_order_and_isolate_conversations():
    engine = create_async_engine(URL, pool_size=20, max_overflow=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    a1, a2, b1, c1 = (uuid.uuid4() for _ in range(4))
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A','fixture_a','Test','active'),(:b,'B','fixture_b','Test','active')"), {"a": t1, "b": t2})
        await conn.execute(text("""
            INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
            VALUES (:a1,:t1,'a1','123','fixture',1,repeat('a',64)),
                   (:a2,:t1,'a2','123','fixture',1,repeat('a',64)),
                   (:b1,:t1,'b1','123','fixture',1,repeat('b',64)),
                   (:c1,:t2,'c1','456','fixture',1,repeat('a',64))
        """), {"a1": a1, "a2": a2, "b1": b1, "c1": c1, "t1": t1, "t2": t2})
    with patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory):
        claims = [c for c in await asyncio.gather(*(claim_next() for _ in range(20))) if c]
        assert {c.id for c in claims} == {a1, b1, c1}
        assert len(claims) == 3
        for claim in claims:
            assert await finish_claim(claim.id, claim.lease_token, uncertain=claim.id == a1)
        assert await claim_next() is None  # uncertain first message blocks only its conversation
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.whatsapp_inbox_events SET state='resolved' WHERE id=:id"), {"id": a1})
        second = await claim_next()
        assert second and second.id == a2
        assert await finish_claim(second.id, second.lease_token, uncertain=False)

        legacy, later, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
                VALUES (:legacy,:t1,'legacy','123','fixture',1,NULL),
                       (:later,:t1,'later','123','fixture',1,repeat('c',64)),
                       (:other,:t2,'other','456','fixture',1,repeat('c',64))
            """), {"legacy": legacy, "later": later, "other": other, "t1": t1, "t2": t2})
        claim = await claim_next()
        assert claim and claim.id == other
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
        assert await claim_next() is None
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE public.whatsapp_inbox_events SET state='resolved' WHERE id=:id"), {"id": legacy})
        claim = await claim_next()
        assert claim and claim.id == later
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_clears_only_terminal_fingerprints():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    completed, uncertain, pending = (uuid.uuid4() for _ in range(3))
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture_retention','Test','active')"), {"id": tenant_id})
        await conn.execute(text("""
            INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint,is_opt_out,state,created_at)
            VALUES (:a,:tenant,'ret-a','123','fixture',1,repeat('a',64),true,'completed',now()-interval '5 days'),
                   (:b,:tenant,'ret-b','123','fixture',1,repeat('b',64),true,'uncertain',now()-interval '5 days'),
                   (:c,:tenant,'ret-c','123','fixture',1,repeat('c',64),true,'pending',now()-interval '5 days')
        """), {"a": completed, "b": uncertain, "c": pending, "tenant": tenant_id})
    with patch("app.services.whatsapp.inbox_retention.get_session_factory", return_value=factory):
        counts = await _redact_tenant(tenant_id, "fixture_retention", 1, datetime.now(UTC))
    assert counts["messages"] == 3
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT id,state,sender_fingerprint,is_opt_out,ciphertext FROM public.whatsapp_inbox_events WHERE tenant_id=:id"), {"id": tenant_id})).all()
    by_id = {row.id: row for row in rows}
    assert by_id[completed].sender_fingerprint is None
    assert not by_id[completed].is_opt_out
    assert by_id[uncertain].sender_fingerprint == "b" * 64
    assert by_id[uncertain].is_opt_out
    assert by_id[pending].state == "uncertain" and by_id[pending].sender_fingerprint == "c" * 64
    assert all(row.ciphertext == "" for row in rows)
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_encrypted_acceptance_preserves_order_across_key_rotation():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "fixture_crypto", "Fixture", "active", {"phone_number_id": "123"})
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_crypto','Test','active',CAST(:cfg AS jsonb))"), {"id": tenant_id, "cfg": '{"phone_number_id":"123"}'})
    kms = KMSService(factory, AsyncMock(), "01" * 32)
    cipher = VersionedEnvelopeService(factory, "01" * 32)
    await kms.generate_tenant_key(tenant_id)
    first = IncomingMessage.model_validate({"id": "msg-1", "from": "212600000001", "timestamp": "1", "type": "text", "text": {"body": "fixture-private"}})
    second = IncomingMessage.model_validate({"id": "msg-2", "from": "212600000001", "timestamp": "2", "type": "text", "text": {"body": "fixture-other"}})
    with (
        patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
        patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory),
    ):
        assert await persist_incoming_message(tenant, "123", first, [], cipher=cipher)
        await kms.rotate_key(tenant_id, tenant.slug)
        assert await persist_incoming_message(tenant, "123", second, [], cipher=cipher)
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT sender_fingerprint,key_version,ciphertext FROM public.whatsapp_inbox_events WHERE tenant_id=:id ORDER BY arrival_sequence"), {"id": tenant_id})).all()
        assert rows[0][0] == rows[1][0] and [row[1] for row in rows] == [1, 2]
        assert all("212600000001" not in row[0] and "fixture-private" not in row[2] for row in rows)
        claim = await claim_next()
        assert claim and (await decrypt_claim(claim, cipher)).message.id == "msg-1"
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
        claim = await claim_next()
        assert claim and (await decrypt_claim(claim, cipher)).message.id == "msg-2"
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_stop_commits_consent_before_ack_and_bypasses_uncertain_messages():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "fixture_stop", "Fixture", "active", {"phone_number_id": "777"})
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_stop','Test','active',CAST(:cfg AS jsonb))"), {"id": tenant_id, "cfg": '{"phone_number_id":"777"}'})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema("fixture_stop")
    kms = KMSService(factory, AsyncMock(), "02" * 32)
    cipher = VersionedEnvelopeService(factory, "02" * 32)
    await kms.generate_tenant_key(tenant_id)
    stop = IncomingMessage.model_validate({"id": "stop-1", "from": "212600000002", "timestamp": "1", "type": "text", "text": {"body": "STOP"}})
    fail_stop = IncomingMessage.model_validate({"id": "stop-fail", "from": "212600000003", "timestamp": "2", "type": "text", "text": {"body": "STOP"}})
    fingerprint = await cipher.whatsapp_sender_fingerprint(tenant_id=tenant_id, channel_id="777", sender_id=stop.from_)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_stop.contacts (phone,opt_in_status) VALUES ('212600000002','opted_in'),('212600000003','opted_in'),('212600000004','opted_in')"))
        await conn.execute(text("""
            INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint,state)
            VALUES (gen_random_uuid(),:id,'older','777','fixture',1,:fingerprint,'uncertain'),
                   (gen_random_uuid(),:id,'legacy-stop-check','777','fixture',1,NULL,'uncertain')
        """), {"id": tenant_id, "fingerprint": fingerprint})
    with (
        patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
        patch("app.core.tenant_lifecycle.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.inbox_leases.get_session_factory", return_value=factory),
    ):
        assert await persist_incoming_message(tenant, "777", stop, [], cipher=cipher)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT opt_in_status::text FROM tenant_fixture_stop.contacts WHERE phone='212600000002'"))).scalar_one() == "opted_out"
            assert (await conn.execute(text("SELECT count(*) FROM public.audit_logs WHERE tenant_slug='fixture_stop' AND action='opt_in_change'"))).scalar_one() == 1
        claim = await claim_next()
        assert claim and claim.is_opt_out and (await decrypt_claim(claim, cipher)).message.id == "stop-1"
        assert await finish_claim(claim.id, claim.lease_token, uncertain=False)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_stop.contacts SET opt_in_status='opted_in' WHERE phone='212600000002'"))
        assert not await persist_incoming_message(tenant, "777", stop, [], cipher=cipher)
        # Simulate a consent-checked provider send already holding the contact
        # lock. STOP cannot be acknowledged until that transaction completes.
        delayed_stop = IncomingMessage.model_validate({"id": "stop-delayed", "from": "212600000004", "timestamp": "3", "type": "text", "text": {"body": "STOP"}})
        async with engine.connect() as sending_connection:
            transaction = await sending_connection.begin()
            await sending_connection.execute(text("SELECT id FROM tenant_fixture_stop.contacts WHERE phone='212600000004' FOR UPDATE"))
            sender_pid = (await sending_connection.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            delayed = asyncio.create_task(persist_incoming_message(tenant, "777", delayed_stop, [], cipher=cipher))
            blocked = False
            try:
                for _ in range(50):
                    async with engine.connect() as monitor:
                        blocked = (await monitor.execute(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid)))"), {"pid": sender_pid})).scalar_one()
                    if blocked:
                        break
                    if delayed.done():
                        break
                    await asyncio.sleep(0.1)
                assert blocked and not delayed.done()
            finally:
                await transaction.commit()
            assert await asyncio.wait_for(delayed, timeout=10)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT opt_in_status::text FROM tenant_fixture_stop.contacts WHERE phone='212600000004'"))).scalar_one() == "opted_out"
        async with engine.begin() as conn:
            assert (await conn.execute(text("SELECT opt_in_status::text FROM tenant_fixture_stop.contacts WHERE phone='212600000002'"))).scalar_one() == "opted_in"
            await conn.execute(text("ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject_optout CHECK (action <> 'opt_in_change') NOT VALID"))
        try:
            with pytest.raises(DBAPIError):
                await persist_incoming_message(tenant, "777", fail_stop, [], cipher=cipher)
            async with engine.connect() as conn:
                assert (await conn.execute(text("SELECT opt_in_status::text FROM tenant_fixture_stop.contacts WHERE phone='212600000003'"))).scalar_one() == "opted_in"
                assert (await conn.execute(text("SELECT count(*) FROM public.whatsapp_inbox_events WHERE tenant_id=:id AND provider_message_id='stop-fail'"), {"id": tenant_id})).scalar_one() == 0
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject_optout"))
    await engine.dispose()
