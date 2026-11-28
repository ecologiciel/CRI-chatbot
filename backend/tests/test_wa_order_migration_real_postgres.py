"""Rehearse the production-specific WhatsApp migration on disposable PostgreSQL."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations

URL = os.getenv("TEST_WA_MIGRATION_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires dedicated disposable PostgreSQL")


@pytest.mark.asyncio
async def test_legacy_inbox_events_are_preserved_and_pending_is_quarantined():
    engine = create_async_engine(URL)
    path = Path(__file__).parents[1] / "alembic/versions/2026_11_28_0019b_whatsapp_order.py"
    spec = importlib.util.spec_from_file_location("wa_order_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    tenant, pending, processing, completed = (uuid.uuid4() for _ in range(4))
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Test','active')"), {"id": tenant, "slug": "wamigration" + tenant.hex})
            for event_id, state in ((pending, "pending"), (processing, "processing"), (completed, "completed")):
                await conn.execute(text("""
                    INSERT INTO public.whatsapp_inbox_events
                      (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version,state,lease_token,lease_until)
                    VALUES (:id,:tenant,:provider,'123','synthetic-ciphertext',1,:state,
                      CASE WHEN CAST(:state AS varchar)='processing' THEN gen_random_uuid() ELSE NULL END,
                      CASE WHEN CAST(:state AS varchar)='processing' THEN now()+interval '5 minutes' ELSE NULL END)
                """), {"id": event_id, "tenant": tenant, "provider": str(event_id), "state": state})

            def run_upgrade(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()

            await conn.run_sync(run_upgrade)
            rows = (await conn.execute(text("SELECT id,state,arrival_sequence,sender_fingerprint,is_opt_out,not_before,ciphertext FROM public.whatsapp_inbox_events WHERE tenant_id=:id"), {"id": tenant})).all()
            by_id = {row.id: row for row in rows}
            assert by_id[pending].state == "uncertain"
            assert by_id[processing].state == "processing"
            assert by_id[completed].state == "completed"
            assert len({row.arrival_sequence for row in rows}) == 3
            assert all(row.sender_fingerprint is None and not row.is_opt_out and row.not_before is None and row.ciphertext == "synthetic-ciphertext" for row in rows)
            indexes = set((await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='whatsapp_inbox_events'"))).scalars())
            assert {"uq_wa_inbox_arrival_sequence", "ix_wa_inbox_conversation_order"} <= indexes
            with pytest.raises(RuntimeError, match="Restore a verified backup"):
                migration.downgrade()
    finally:
        await engine.dispose()
