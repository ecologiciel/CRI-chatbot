"""Real PostgreSQL tests; run only against an explicitly supplied disposable database."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.services.notification import outbox_execution as execution
from app.services.notification.outbox import (
    claim_notification,
    enqueue_notification,
    finish_notification,
    quarantine_expired_notifications,
)

DB_URL = os.environ.get("TEST_NOTIFICATION_OUTBOX_DB_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="requires dedicated disposable PostgreSQL database"
)


@pytest.mark.asyncio()
async def test_outbox_transaction_isolation_and_fenced_leases(monkeypatch):
    engine = create_async_engine(DB_URL)
    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/2026_11_27_0020_notification_outbox.py"
    )
    spec = importlib.util.spec_from_file_location("outbox_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply_migration(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE public.tenants (id uuid PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE public.test_dossier_history (id uuid PRIMARY KEY)"))
        await conn.run_sync(apply_migration)
        await conn.execute(
            text("INSERT INTO public.tenants VALUES (:a), (:b)"), {"a": tenant_a, "b": tenant_b}
        )

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    history_a, history_b, rolled_back = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sessions() as session:
        await session.execute(
            text("INSERT INTO public.test_dossier_history VALUES (:id)"), {"id": rolled_back}
        )
        assert await enqueue_notification(session, tenant_a, rolled_back)
        await session.rollback()
    async with sessions.begin() as session:
        assert not (
            await session.execute(
                text("SELECT 1 FROM public.test_dossier_history WHERE id=:id"), {"id": rolled_back}
            )
        ).first()
        assert await enqueue_notification(session, tenant_a, history_a)
        assert not await enqueue_notification(session, tenant_a, history_a)
        assert await enqueue_notification(session, tenant_b, history_b)

    # Both claims overlap: one row can only be claimed by one worker.
    locked = asyncio.Event()
    release = asyncio.Event()

    async def first_worker():
        async with sessions.begin() as session:
            claim = await claim_notification(session, tenant_a)
            locked.set()
            await release.wait()
            return claim

    task = asyncio.create_task(first_worker())
    await asyncio.wait_for(locked.wait(), 5)
    async with sessions.begin() as session:
        assert await claim_notification(session, tenant_a) is None
        other = await claim_notification(session, tenant_b)
        assert other.history_id == history_b
    release.set()
    claim = await task
    assert claim.history_id == history_a

    async with sessions.begin() as session:
        assert not await finish_notification(
            session,
            tenant_b,
            claim,
            outcome="sent",
            outcome_code="provider_accepted",
            provider_message_id="wamid.test",
        )
        assert await finish_notification(
            session,
            tenant_a,
            claim,
            outcome="sent",
            outcome_code="provider_accepted",
            provider_message_id="wamid.test",
        )
        assert not await finish_notification(
            session,
            tenant_a,
            claim,
            outcome="sent",
            outcome_code="provider_accepted",
            provider_message_id="wamid.test",
        )
        await session.execute(
            text(
                "UPDATE public.notification_outbox_events SET lease_until=now()-interval '1 second' "
                "WHERE tenant_id=:tenant AND state='processing'"
            ),
            {"tenant": tenant_b},
        )
        assert await quarantine_expired_notifications(session, tenant_a) == 0
        assert await quarantine_expired_notifications(session, tenant_b) == 1
        assert not await finish_notification(
            session,
            tenant_b,
            other,
            outcome="sent",
            outcome_code="provider_accepted",
            provider_message_id="wamid.test",
        )
        assert await claim_notification(session, tenant_b) is None
        rows = (
            await session.execute(
                text("SELECT tenant_id, state, outcome_code FROM public.notification_outbox_events")
            )
        ).all()
        assert {(r.tenant_id, r.state, r.outcome_code) for r in rows} == {
            (tenant_a, "sent", "provider_accepted"),
            (tenant_b, "uncertain", "lease_expired"),
        }

    @asynccontextmanager
    async def db_session():
        async with sessions.begin() as session:
            yield session

    tenant = SimpleNamespace(id=tenant_a, db_session=db_session)
    service = SimpleNamespace(
        send_notification=AsyncMock(return_value={"status": "sent", "wamid": "wamid.integration"})
    )
    monkeypatch.setattr(execution, "_load_change", AsyncMock(return_value=object()))
    async with sessions.begin() as session:
        assert await enqueue_notification(session, tenant_a, uuid.uuid4())
    assert await execution.process_one_notification(tenant, service) == "sent"
    assert await execution.process_one_notification(tenant, service) == "empty"
    service.send_notification.assert_awaited_once()
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM public.notification_outbox_events "
                    "WHERE tenant_id=:tenant AND state='sent' AND provider_message_id='wamid.integration'"
                ),
                {"tenant": tenant_a},
            )
        ).scalar_one() == 1
    await engine.dispose()
