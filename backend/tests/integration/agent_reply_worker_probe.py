"""Run the actual ARQ agent worker on isolated synthetic services only.

The provider is replaced with a fake. This is not a Meta integration test or
capacity benchmark and must never run against a real institution database.
"""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock

from arq.worker import Worker
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation.reply_outbox import register_agent_reply
from app.services.escalation.reply_presence import HEARTBEAT_KEY
from app.services.tenant.provisioning import TenantProvisioningService
from app.workers import agent_reply_outbox as worker_module


async def main() -> None:
    if (os.environ.get("POSTGRES_DB") != "ragtest_agent_worker"
            or os.environ.get("POSTGRES_USER") != "fixture"
            or not os.environ.get("REDIS_HOST", "").startswith("codex-agent-redis-")):
        raise RuntimeError("Refusing to run outside the disposable agent worker fixture")
    settings = get_settings()
    if not settings.agent_reply_outbox_enabled or settings.kms_master_key != "07" * 32:
        raise RuntimeError("Invalid synthetic worker configuration")
    factory = get_session_factory()
    tid, actor, contact, conversation, escalation = (uuid.uuid4() for _ in range(5))
    tenant = TenantContext(tid, "fixture_agent_worker", "Fixture", "active", None)
    async with factory() as session:
        assert (await session.scalar(text("SELECT current_database()"))) == "ragtest_agent_worker"
        await session.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_agent_worker','Test','active','{\"phone_number_id\":\"979\",\"access_token\":\"fixture\"}')"), {"id": tid})
        await session.execute(text("INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id) VALUES (:id,'agent-worker@example.test','fixture','Fixture','admin_tenant',:tenant)"), {"id": actor, "tenant": tid})
        await session.commit()
    await TenantProvisioningService()._create_schema(tenant.slug)
    async with factory() as session:
        await session.execute(text("INSERT INTO tenant_fixture_agent_worker.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000077','opted_in')"), {"id": contact})
        await session.execute(text("INSERT INTO tenant_fixture_agent_worker.conversations (id,contact_id,status) VALUES (:id,:contact,'human_handled')"), {"id": conversation, "contact": contact})
        await session.execute(text("INSERT INTO tenant_fixture_agent_worker.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','assigned')"), {"id": escalation, "conversation": conversation})
        await session.commit()
    cipher = VersionedEnvelopeService(factory, settings.kms_master_key)
    await KMSService(factory, AsyncMock(), settings.kms_master_key).generate_tenant_key(tid)
    first = await register_agent_reply(tenant, escalation, actor, uuid.uuid4(), "fixture-0", cipher=cipher)
    # Synthesize a pre-existing backlog to verify that the worker still fences
    # old data. New API registrations now allow just one outstanding request.
    for i in (1, 2):
        event_id = uuid.uuid4()
        encrypted = await cipher.encrypt(
            f"fixture-{i}".encode(), tenant_id=tid, purpose="agent_reply", record_id=event_id,
        )
        async with factory() as session:
            await session.execute(text("""
                INSERT INTO public.agent_reply_outbox_events
                    (id,tenant_id,request_key,actor_id,escalation_id,conversation_id,contact_id,
                     phone_number_id,recipient_fingerprint,ciphertext,key_version)
                SELECT :id,tenant_id,:request,actor_id,escalation_id,conversation_id,contact_id,
                       phone_number_id,recipient_fingerprint,:ciphertext,:version
                FROM public.agent_reply_outbox_events WHERE id=:first
            """), {"id": event_id, "request": uuid.uuid4(), "ciphertext": encrypted.ciphertext,
                     "version": encrypted.version, "first": first.id})
            await session.commit()
    sends: list[str] = []

    class FakeSender:
        async def send_text(self, _tenant, _phone, body):
            sends.append(body)
            if body == "fixture-1":
                raise TimeoutError("synthetic ambiguous provider outcome")
            return "synthetic-provider-id"

    original = worker_module.WhatsAppSenderService
    worker_module.WhatsAppSenderService = FakeSender
    worker = Worker(
        functions=worker_module.WorkerSettings.functions,
        cron_jobs=worker_module.WorkerSettings.cron_jobs,
        redis_settings=worker_module.WorkerSettings.redis_settings,
        on_startup=worker_module.startup,
        on_shutdown=worker_module.shutdown,
        queue_name="arq:fixture-agent-reply",
        max_jobs=1, max_tries=1, poll_delay=0.2, handle_signals=False,
    )
    runner = asyncio.create_task(worker.async_run())
    try:
        states = []
        for _ in range(180):
            if runner.done():
                await runner
                raise RuntimeError("Worker exited unexpectedly")
            async with factory() as session:
                states = (await session.execute(text("SELECT state FROM public.agent_reply_outbox_events WHERE tenant_id=:id ORDER BY sequence"), {"id": tid})).scalars().all()
            if states == ["accepted", "uncertain", "pending"]:
                break
            await asyncio.sleep(0.25)
        assert states == ["accepted", "uncertain", "pending"], states
        assert sends == ["fixture-0", "fixture-1"], sends
        assert await get_redis().exists(HEARTBEAT_KEY)
        assert len(states) == 3
        print("AGENT_REPLY_REAL_ARQ_ORDER_UNCERTAINTY_PRESENCE_OK", flush=True)
    finally:
        await worker.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        worker_module.WhatsAppSenderService = original


if __name__ == "__main__":
    asyncio.run(main())
