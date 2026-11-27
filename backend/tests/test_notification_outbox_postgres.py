"""Real PostgreSQL tests; run only against an explicitly supplied disposable database."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.api.v1 import whatsapp_operations as operations
from app.services.notification import outbox_execution as execution
from app.services.notification import outbox_retention as retention
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
        await conn.execute(
            text("""
            CREATE TABLE public.audit_logs (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_slug varchar(50) NOT NULL,
                user_id uuid, user_type varchar(20) NOT NULL, action varchar(20) NOT NULL,
                resource_type varchar(100) NOT NULL, resource_id varchar(255),
                ip_address varchar(45), user_agent text, details jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT test_reject_review CHECK (action <> 'notif_outbox_review')
            )
        """)
        )
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
        assert await enqueue_notification(
            session, tenant_a, rolled_back, uuid.uuid4(), uuid.uuid4()
        )
        await session.rollback()
    async with sessions.begin() as session:
        assert not (
            await session.execute(
                text("SELECT 1 FROM public.test_dossier_history WHERE id=:id"), {"id": rolled_back}
            )
        ).first()
        assert await enqueue_notification(session, tenant_a, history_a, uuid.uuid4(), uuid.uuid4())
        assert not await enqueue_notification(
            session, tenant_a, history_a, uuid.uuid4(), uuid.uuid4()
        )
        assert await enqueue_notification(session, tenant_b, history_b, uuid.uuid4(), uuid.uuid4())

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

    monkeypatch.setattr(operations, "get_session_factory", lambda: sessions)
    review_tenant = SimpleNamespace(id=tenant_b, slug="test_b")
    reviewer = SimpleNamespace(sub=str(uuid.uuid4()))
    async with sessions.begin() as session:
        event_id = (
            await session.execute(
                text("SELECT id FROM public.notification_outbox_events WHERE tenant_id=:tenant"),
                {"tenant": tenant_b},
            )
        ).scalar_one()
    with pytest.raises(IntegrityError):
        await operations.review_event(
            event_id,
            operations.ReviewRequest(action="follow_up"),
            kind="notification",
            tenant=review_tenant,
            admin=reviewer,
        )
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text("SELECT state FROM public.notification_outbox_events WHERE id=:id"),
                {"id": event_id},
            )
        ).scalar_one() == "uncertain"
        await session.execute(
            text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_reject_review")
        )
    result = await operations.review_event(
        event_id,
        operations.ReviewRequest(action="follow_up"),
        kind="notification",
        tenant=review_tenant,
        admin=reviewer,
    )
    assert result["state"] == "follow_up"
    with pytest.raises(HTTPException) as wrong_tenant:
        await operations.review_event(
            event_id,
            operations.ReviewRequest(action="resolve"),
            kind="notification",
            tenant=SimpleNamespace(id=tenant_a, slug="test_a"),
            admin=reviewer,
        )
    assert wrong_tenant.value.status_code == 404
    with pytest.raises(HTTPException) as duplicate:
        await operations.review_event(
            event_id,
            operations.ReviewRequest(action="follow_up"),
            kind="notification",
            tenant=review_tenant,
            admin=reviewer,
        )
    assert duplicate.value.status_code == 409
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM public.audit_logs WHERE tenant_slug='test_b' AND action='notif_outbox_review'"
                )
            )
        ).scalar_one() == 1

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
        assert await enqueue_notification(
            session, tenant_a, uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        )
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
    monkeypatch.setattr(retention, "get_session_factory", lambda: sessions)
    pending_id, active_id, expired_id, foreign_id = (uuid.uuid4() for _ in range(4))
    async with sessions.begin() as session:
        for event_id, tenant_id, state, lease in (
            (pending_id, tenant_a, "pending", None),
            (active_id, tenant_a, "processing", "future"),
            (expired_id, tenant_a, "processing", "past"),
            (foreign_id, tenant_b, "pending", None),
        ):
            await session.execute(
                text("""
                INSERT INTO public.notification_outbox_events
                (id,tenant_id,history_id,dossier_id,contact_id,state,lease_token,lease_until,provider_message_id,created_at)
                VALUES (:id,:tenant,:history,:dossier,:contact,:state,:token,
                        CASE WHEN :lease = 'future' THEN now()+interval '1 hour'
                             WHEN :lease = 'past' THEN now()-interval '1 hour' ELSE NULL END,
                        'wamid.private',now()-interval '40 days')
            """),
                {
                    "id": event_id,
                    "tenant": tenant_id,
                    "history": uuid.uuid4(),
                    "dossier": uuid.uuid4(),
                    "contact": uuid.uuid4(),
                    "state": state,
                    "token": uuid.uuid4() if lease else None,
                    "lease": lease,
                },
            )
        await session.execute(
            text(
                "ALTER TABLE public.audit_logs ADD CONSTRAINT test_reject_purge CHECK (action <> 'notif_outbox_purge')"
            )
        )
    with pytest.raises(IntegrityError):
        await retention.redact_tenant_outbox(tenant_a, "test_a", 30, datetime.now(UTC))
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM public.notification_outbox_events WHERE id IN (:a,:b) AND redacted_at IS NOT NULL"
                ),
                {"a": pending_id, "b": expired_id},
            )
        ).scalar_one() == 0
        await session.execute(
            text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_reject_purge")
        )
    assert await retention.redact_tenant_outbox(tenant_a, "test_a", 30, datetime.now(UTC)) == 2
    async with sessions.begin() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id,state,contact_id,provider_message_id,redacted_at,outcome_code FROM public.notification_outbox_events WHERE id IN (:a,:b,:c,:d)"
                ),
                {"a": pending_id, "b": expired_id, "c": active_id, "d": foreign_id},
            )
        ).all()
        by_id = {row.id: row for row in rows}
        for event_id in (pending_id, expired_id):
            row = by_id[event_id]
            assert row.state == "uncertain" and row.contact_id is None
            assert row.provider_message_id is None and row.redacted_at is not None
            assert row.outcome_code == "retention_expired"
        assert by_id[active_id].redacted_at is None
        assert by_id[foreign_id].redacted_at is None
    await engine.dispose()
