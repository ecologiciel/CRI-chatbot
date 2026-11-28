"""Escalation audit and consent against a disposable PostgreSQL database."""
import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import EscalationConflictError
from app.core.tenant import TenantContext
from app.models.enums import EscalationTrigger
from app.services.escalation.service import EscalationService
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_ESCALATION_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_escalation_audit_is_atomic_and_stop_prevents_further_sends():
    engine = create_async_engine(URL, pool_size=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tid, admin, contact_id, conversation_id = (uuid.uuid4() for _ in range(4))
    tenant = TenantContext(tid, "fixtureaudit", "Fixture", "active", None)
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixtureaudit','Test','active')"), {"id": tid})
        await conn.execute(text("INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id) VALUES (:id,'fixture@example.test','fixture','A','admin_tenant',:tenant)"), {"id": admin, "tenant": tid})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(tenant.slug)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixtureaudit.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000001','opted_in')"), {"id": contact_id})
        await conn.execute(text("INSERT INTO tenant_fixtureaudit.conversations (id,contact_id,status) VALUES (:id,:contact,'active')"), {"id": conversation_id, "contact": contact_id})
    sender = AsyncMock()
    sender.send_text.return_value = "fixture-wamid"
    service = EscalationService(gemini=AsyncMock(), sender=sender, audit=AsyncMock())
    service.generate_context_summary = AsyncMock(return_value=None)
    redis = AsyncMock()

    async def block_audit(action):
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER TABLE public.audit_logs ADD CONSTRAINT fixture_reject CHECK (action <> '{action}' OR tenant_slug <> 'fixtureaudit') NOT VALID"))

    async def unblock_audit():
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE public.audit_logs DROP CONSTRAINT fixture_reject"))

    with (patch("app.core.tenant.get_session_factory", return_value=factory),
          patch("app.services.escalation.service.get_redis", return_value=redis)):
        await block_audit("create")
        try:
            with pytest.raises(DBAPIError):
                await service.create_escalation(conversation_id, EscalationTrigger.explicit_request, None, tenant)
        finally:
            await unblock_audit()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM tenant_fixtureaudit.escalations")) == 0
            assert await conn.scalar(text("SELECT status::text FROM tenant_fixtureaudit.conversations WHERE id=:id"), {"id": conversation_id}) == "active"
        redis.publish.assert_not_awaited()
        escalation = await service.create_escalation(conversation_id, EscalationTrigger.explicit_request, None, tenant)
        eid = escalation.id
        await block_audit("assign")
        try:
            with pytest.raises(DBAPIError):
                await service.assign_escalation(eid, admin, tenant)
        finally:
            await unblock_audit()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT status::text FROM tenant_fixtureaudit.escalations WHERE id=:id"), {"id": eid}) == "pending"
            assert await conn.scalar(text("SELECT status::text FROM tenant_fixtureaudit.conversations WHERE id=:id"), {"id": conversation_id}) == "escalated"
        await service.assign_escalation(eid, admin, tenant)
        # STOP waits for an already-started provider call to leave the
        # contact lock; future replies must then observe the opt-out.
        started, release = asyncio.Event(), asyncio.Event()
        async def provider_send(*_args, **_kwargs):
            started.set()
            await release.wait()
            return "fixture-wamid"
        sender.send_text.side_effect = provider_send
        reply = asyncio.create_task(service.respond_via_whatsapp(eid, "fixture", admin, tenant))
        await asyncio.wait_for(started.wait(), timeout=10)
        async with engine.connect() as conn:
            tx = await conn.begin()
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            stop = asyncio.create_task(conn.execute(text("UPDATE tenant_fixtureaudit.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": contact_id}))
            try:
                blocked = False
                for _ in range(50):
                    async with engine.connect() as monitor:
                        blocked = bool(await monitor.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}))
                    if blocked or stop.done():
                        break
                    await asyncio.sleep(0.1)
                assert blocked and not stop.done()
            finally:
                release.set()
            assert await asyncio.wait_for(reply, timeout=10) == "fixture-wamid"
            await asyncio.wait_for(stop, timeout=10)
            await tx.commit()
        sender.send_text.reset_mock(side_effect=True)
        await block_audit("close")
        try:
            with pytest.raises(DBAPIError):
                await service.close_escalation(eid, "fixture", admin, tenant)
        finally:
            await unblock_audit()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT status::text FROM tenant_fixtureaudit.escalations WHERE id=:id"), {"id": eid}) == "in_progress"
            assert await conn.scalar(text("SELECT status::text FROM tenant_fixtureaudit.conversations WHERE id=:id"), {"id": conversation_id}) == "human_handled"
        sender.send_text.assert_not_awaited()
        with pytest.raises(EscalationConflictError):
            await service.respond_via_whatsapp(eid, "fixture", admin, tenant)
        await service.close_escalation(eid, "fixture", admin, tenant)
        sender.send_text.assert_not_awaited()
        async with engine.connect() as conn:
            actions = (await conn.execute(text("SELECT action FROM public.audit_logs WHERE tenant_slug='fixtureaudit' ORDER BY created_at"))).scalars().all()
            assert actions == ["create", "assign", "close"]
    await engine.dispose()
