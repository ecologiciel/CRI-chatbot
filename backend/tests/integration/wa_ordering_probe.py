"""Check per-conversation ordering with real PostgreSQL, Redis and ARQ.

Run only in an isolated fixture; handler effects are simulated and no external
provider is called. This probes current behavior, not a production load test.
"""

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
    if os.environ.get("POSTGRES_DB") != "ragtest_wa_order" or os.environ.get("POSTGRES_USER") != "fixture":
        raise RuntimeError("Refusing to run outside the WhatsApp ordering fixture")
    os.environ["WHATSAPP_DURABLE_INBOX_ENABLED"] = "true"
    get_settings.cache_clear()
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    first_id, second_id, other_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with factory() as session:
        assert (await session.execute(text("SELECT current_database()"))).scalar_one() == "ragtest_wa_order"
        await session.execute(
            text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture','Test','active')"),
            {"id": tenant_id},
        )
        await session.execute(
            text("""
                INSERT INTO public.whatsapp_inbox_events
                  (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,sender_fingerprint)
                VALUES (:a,:tenant,'synthetic-first','123','fixture',1,repeat('a',64)),
                       (:b,:tenant,'synthetic-second','123','fixture',1,repeat('a',64)),
                       (:c,:tenant,'synthetic-other','123','fixture',1,repeat('b',64))
            """),
            {"a": first_id, "b": second_id, "c": other_id, "tenant": tenant_id},
        )
        await session.commit()

    completion_order: list[str] = []

    async def fake_process(claim):
        if claim.id == first_id:
            await asyncio.sleep(16)
            completion_order.append("first")
        elif claim.id == second_id:
            completion_order.append("second")
        elif claim.id == other_id:
            completion_order.append("other")
        return HandlingOutcome.accepted

    original = inbox_execution._process
    inbox_execution._process = fake_process
    worker = Worker(
        functions=[],
        cron_jobs=[cron(drain_incoming, second={0, 10, 20, 30, 40, 50})],
        redis_settings=_get_redis_settings(),
        queue_name="arq:fixture-wa-order",
        max_jobs=3,
        max_tries=1,
        poll_delay=0.2,
        handle_signals=False,
    )
    runner = asyncio.create_task(worker.async_run())
    try:
        for _ in range(350):
            if len(completion_order) == 3:
                break
            if runner.done():
                await runner
                raise RuntimeError("Worker exited unexpectedly")
            await asyncio.sleep(0.2)
        assert completion_order == ["other", "first", "second"], completion_order
        print("WA_ORDERED_CONVERSATIONS_WITH_CROSS_CONVERSATION_CONCURRENCY_OK", flush=True)
    finally:
        await worker.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        inbox_execution._process = original
        await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
