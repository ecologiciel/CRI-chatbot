"""Measure scheduler-only throughput on isolated synthetic conversations.

This intentionally replaces the provider/AI handler with an immediate fake;
the result is not a real user, network, provider or end-to-end load test.
"""

import asyncio
import os
import time
import uuid

from arq import cron
from arq.worker import Worker
from sqlalchemy import text

from app.core.database import close_engine, get_session_factory
from app.services.whatsapp import inbox_execution
from app.services.whatsapp.handler import HandlingOutcome
from app.workers.whatsapp_inbox import _get_redis_settings, poll_incoming


async def main() -> None:
    if os.environ.get("POSTGRES_DB") != "ragtest_wa_load" or os.environ.get("POSTGRES_USER") != "fixture":
        raise RuntimeError("Refusing to run outside the WhatsApp load fixture")
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session:
        assert (await session.execute(text("SELECT current_database()"))).scalar_one() == "ragtest_wa_load"
        await session.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture_load','Test','active')"), {"id": tenant_id})
        await session.execute(
            text("""
                INSERT INTO public.whatsapp_inbox_events
                  (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
                VALUES (:id,:tenant,:provider,'123','fixture',1,:fingerprint)
            """),
            [{"id": uuid.uuid4(), "tenant": tenant_id, "provider": f"synthetic-{i}", "fingerprint": f"{i:064x}"} for i in range(12)],
        )
        await session.commit()

    async def fake_process(_claim):
        return HandlingOutcome.accepted

    original = inbox_execution._process
    inbox_execution._process = fake_process
    worker = Worker(
        functions=[], cron_jobs=[cron(poll_incoming, second={0, 10, 20, 30, 40, 50})],
        redis_settings=_get_redis_settings(), queue_name="arq:fixture-wa-load",
        max_jobs=3, max_tries=1, poll_delay=0.2, handle_signals=False,
    )
    runner = asyncio.create_task(worker.async_run())
    start = time.monotonic()
    try:
        await asyncio.sleep(25)
        if runner.done():
            await runner
            raise RuntimeError("Worker exited unexpectedly")
    finally:
        await worker.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        inbox_execution._process = original
    async with factory() as session:
        completed = (await session.execute(text("SELECT count(*) FROM public.whatsapp_inbox_events WHERE tenant_id=:id AND state='completed'"), {"id": tenant_id})).scalar_one()
    elapsed = time.monotonic() - start
    assert 1 <= completed <= 4, completed
    print(f"SYNTHETIC_SCHEDULER_CAPACITY completed={completed} queued=12 seconds={elapsed:.1f}", flush=True)
    await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
