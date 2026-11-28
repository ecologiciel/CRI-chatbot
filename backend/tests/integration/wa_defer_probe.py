"""Exercise deferred ordering with a real ARQ worker and disposable services."""

import asyncio
import os
import uuid

from arq import cron
from arq.worker import Worker
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import close_engine, get_session_factory
from app.services.whatsapp import inbox_execution
from app.services.whatsapp.handler import HandlingOutcome
from app.workers.whatsapp_inbox import _get_redis_settings, drain_incoming


async def main() -> None:
    if os.environ.get("POSTGRES_DB") != "ragtest_wa_defer" or os.environ.get("POSTGRES_USER") != "fixture":
        raise RuntimeError("Refusing to run outside the WhatsApp deferral fixture")
    get_settings().whatsapp_durable_inbox_enabled = True
    factory = get_session_factory()
    tenant, first, second, other = (uuid.uuid4() for _ in range(4))
    async with factory() as session:
        assert (await session.execute(text("SELECT current_database()"))).scalar_one() == "ragtest_wa_defer"
        await session.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture_defer','Test','active')"), {"id": tenant})
        await session.execute(text("""
            INSERT INTO public.whatsapp_inbox_events
              (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
            VALUES (:a,:t,'first','123','fixture',1,repeat('a',64)),
                   (:b,:t,'second','123','fixture',1,repeat('a',64)),
                   (:c,:t,'other','123','fixture',1,repeat('b',64))
        """), {"a": first, "b": second, "c": other, "t": tenant})
        await session.commit()

    calls: list[uuid.UUID] = []

    async def fake_process(claim):
        calls.append(claim.id)
        if claim.id == first and calls.count(first) == 1:
            return HandlingOutcome.deferred
        return HandlingOutcome.accepted

    original = inbox_execution._process
    inbox_execution._process = fake_process
    worker = Worker(functions=[], cron_jobs=[cron(drain_incoming, second={0, 10, 20, 30, 40, 50})],
                    redis_settings=_get_redis_settings(), queue_name="arq:fixture-wa-defer",
                    max_jobs=3, max_tries=1, poll_delay=0.2, handle_signals=False)
    runner = asyncio.create_task(worker.async_run())
    try:
        for _ in range(150):
            async with factory() as session:
                deferred = (await session.execute(text("SELECT state, not_before > clock_timestamp() FROM public.whatsapp_inbox_events WHERE id=:id"), {"id": first})).one()
            if deferred == ("pending", True) and other in calls:
                break
            if runner.done():
                await runner
                raise RuntimeError("Worker exited unexpectedly")
            await asyncio.sleep(0.2)
        assert calls.count(first) == 1 and other in calls and second not in calls, calls
        async with factory() as session:
            assert deferred == ("pending", True)
            await session.execute(text("UPDATE public.whatsapp_inbox_events SET not_before=now()-interval '1 second' WHERE id=:id"), {"id": first})
            await session.commit()
        for _ in range(150):
            if calls.count(first) == 2 and second in calls:
                break
            if runner.done():
                await runner
                raise RuntimeError("Worker exited unexpectedly")
            await asyncio.sleep(0.2)
        assert calls.index(second) > len(calls) - 1 - calls[::-1].index(first), calls
        print("WA_DEFER_REAL_ARQ_ORDER_OK", flush=True)
    finally:
        await worker.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        inbox_execution._process = original
        await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
