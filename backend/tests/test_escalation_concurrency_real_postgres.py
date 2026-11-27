"""Transactional escalation transitions against a disposable database."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import EscalationConflictError
from app.core.tenant import TenantContext
from app.services.escalation.service import EscalationService
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_only_one_agent_claims_and_closed_escalation_cannot_be_reopened():
    engine = create_async_engine(URL, pool_size=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tid, admin_a, admin_b, cid, conversation_id, escalation_id = (uuid.uuid4() for _ in range(6))
    tenant = TenantContext(tid, "fixture_escalation", "Fixture", "active", None)
    async with engine.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture_escalation','Test','active')"), {"id": tid})
        await conn.execute(text("""
            INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id)
            VALUES (:a,'fixture-a@example.test','fixture','A','admin_tenant',:tenant),
                   (:b,'fixture-b@example.test','fixture','B','admin_tenant',:tenant)
        """), {"a": admin_a, "b": admin_b, "tenant": tid})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema(tenant.slug)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_escalation.contacts (id,phone) VALUES (:id,'+212600000001')"), {"id": cid})
        await conn.execute(text("INSERT INTO tenant_fixture_escalation.conversations (id,contact_id,status) VALUES (:id,:contact,'escalated')"), {"id": conversation_id, "contact": cid})
        await conn.execute(text("INSERT INTO tenant_fixture_escalation.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','pending')"), {"id": escalation_id, "conversation": conversation_id})
    sender = AsyncMock()
    started, release = asyncio.Event(), asyncio.Event()

    async def provider_send(*_args, **_kwargs):
        started.set()
        await release.wait()
        return "fixture-wamid"

    sender.send_text.side_effect = provider_send
    service = EscalationService(gemini=AsyncMock(), sender=sender, audit=AsyncMock())
    with (patch("app.core.tenant.get_session_factory", return_value=factory),
          patch("app.services.escalation.service.get_redis", return_value=AsyncMock())):
        results = await asyncio.gather(
            service.assign_escalation(escalation_id, admin_a, tenant),
            service.assign_escalation(escalation_id, admin_b, tenant),
            return_exceptions=True,
        )
        assert sum(isinstance(result, EscalationConflictError) for result in results) == 1
        winner = next(result.assigned_to for result in results if not isinstance(result, Exception))
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT status::text,assigned_to FROM tenant_fixture_escalation.escalations WHERE id=:id"), {"id": escalation_id})).one()
            assert row.status == "assigned" and row.assigned_to == winner
        assert service._audit.log_action.await_count == 1
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_escalation.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": cid})
        with pytest.raises(EscalationConflictError):
            await service.respond_via_whatsapp(escalation_id, "fixture", winner, tenant)
        sender.send_text.assert_not_awaited()
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenant_fixture_escalation.contacts SET opt_in_status='opted_in' WHERE id=:id"), {"id": cid})
        response = asyncio.create_task(service.respond_via_whatsapp(escalation_id, "fixture", winner, tenant))
        await asyncio.wait_for(started.wait(), timeout=10)
        async with engine.connect() as stopper:
            transaction = await stopper.begin()
            stopper_pid = (await stopper.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            stop = asyncio.create_task(stopper.execute(text("UPDATE tenant_fixture_escalation.contacts SET opt_in_status='opted_out' WHERE id=:id"), {"id": cid}))
            blocked = False
            try:
                for _ in range(50):
                    async with engine.connect() as monitor:
                        blocked = (await monitor.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": stopper_pid}))
                    if blocked or stop.done():
                        break
                    await asyncio.sleep(0.1)
                assert blocked and not stop.done()
            finally:
                release.set()
            assert await asyncio.wait_for(response, timeout=10) == "fixture-wamid"
            await asyncio.wait_for(stop, timeout=10)
            await transaction.commit()
        await service.close_escalation(escalation_id, "fixture", winner, tenant)
        with pytest.raises(EscalationConflictError):
            await service.assign_escalation(escalation_id, admin_b, tenant)
        with pytest.raises(EscalationConflictError):
            await service.respond_via_whatsapp(escalation_id, "fixture", admin_b, tenant)
        with pytest.raises(EscalationConflictError):
            await service.close_escalation(escalation_id, "fixture", admin_b, tenant)
        # STOP committed before closure, so only the earlier response was sent.
        assert sender.send_text.await_count == 1
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT status::text FROM tenant_fixture_escalation.conversations WHERE id=:id"), {"id": conversation_id})) == "active"
    await engine.dispose()
