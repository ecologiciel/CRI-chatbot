"""Exercise the real row locks on a separate disposable PostgreSQL database."""

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
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.contact import Contact
from app.models.dossier import Dossier, DossierHistory
from app.models.sync import SyncLog
from app.models.tenant import Tenant
from app.services.dossier.import_service import DossierImportRow, DossierImportService
from app.services.notification.outbox import claim_notification, enqueue_notification
from app.services.notification.outbox_execution import process_one_notification
from app.services.notification.service import NotificationService

URL = os.environ.get("TEST_NOTIFICATION_GUARD_DB_URL")
pytestmark = pytest.mark.skipif(
    not URL, reason="requires a separate disposable PostgreSQL database"
)


@pytest.mark.asyncio()
async def test_dossier_lock_serializes_changes_during_provider_send():
    engine = create_async_engine(
        URL, connect_args={"server_settings": {"search_path": "tenant_guard,public"}}
    )
    metadata = sa.MetaData()

    # Tables use the real mapped columns; constraints unrelated to this test are omitted.
    for model, schema in [
        (Tenant, "public"),
        (Dossier, "tenant_guard"),
        (DossierHistory, "tenant_guard"),
        (Contact, "tenant_guard"),
        (SyncLog, "tenant_guard"),
    ]:
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name, col.type, primary_key=col.primary_key, nullable=not col.primary_key
                )
                for col in model.__table__.columns
            ],
            schema=schema,
        )

    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/2026_11_27_0020_notification_outbox.py"
    )
    spec = importlib.util.spec_from_file_location("guard_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def install(connection):
        metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    tenant_id, dossier_id, contact_id, history_id = (uuid.uuid4() for _ in range(4))
    config = {"phone_number_id": "123", "access_token": "test"}
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA tenant_guard"))
        await conn.run_sync(install)
        await conn.execute(
            sa.text(
                "INSERT INTO public.tenants (id,status,whatsapp_config) VALUES (:id,'active',CAST(:cfg AS jsonb))"
            ),
            {"id": tenant_id, "cfg": '{"phone_number_id":"123","access_token":"test"}'},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO tenant_guard.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000000','opted_in')"
            ),
            {"id": contact_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO tenant_guard.dossiers (id,numero,contact_id,statut) VALUES (:id,'A',:contact,'valide')"
            ),
            {"id": dossier_id, "contact": contact_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO tenant_guard.dossier_history (id,dossier_id,field_changed,new_value,old_value) VALUES (:id,:dossier,'statut','valide','en_attente')"
            ),
            {"id": history_id, "dossier": dossier_id},
        )

    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def db_session():
        async with sessions.begin() as session:
            yield session

    tenant = SimpleNamespace(
        id=tenant_id, slug="guard", whatsapp_config=config, db_session=db_session
    )
    newer_history_id = uuid.uuid4()
    async with sessions.begin() as session:
        assert await enqueue_notification(session, tenant_id, history_id, dossier_id, contact_id)
        claim = await claim_notification(session, tenant_id)

    entered, release = asyncio.Event(), asyncio.Event()

    async def send(**kwargs):
        entered.set()
        await release.wait()
        return "wamid.accepted"

    sender = SimpleNamespace(send_template=AsyncMock(side_effect=send))
    service = NotificationService(sender, AsyncMock())
    running = asyncio.create_task(
        service._send_with_current_consent(
            tenant,
            contact_id,
            template_name="x",
            language_code="fr",
            components=[],
            durable_claim=claim,
            expected_status="valide",
            expected_old_status="en_attente",
        )
    )
    await asyncio.wait_for(entered.wait(), 10)

    async def update_dossier():
        async with sessions.begin() as session:
            await session.execute(
                sa.text("UPDATE tenant_guard.dossiers SET statut='rejete' WHERE id=:id"),
                {"id": dossier_id},
            )

    updater = asyncio.create_task(update_dossier())
    await asyncio.sleep(0.2)
    assert not updater.done()
    release.set()
    assert await running == (None, "wamid.accepted")
    await asyncio.wait_for(updater, 10)
    reason, wamid = await service._send_with_current_consent(
        tenant,
        contact_id,
        template_name="x",
        language_code="fr",
        components=[],
        durable_claim=claim,
        expected_status="valide",
        expected_old_status="en_attente",
    )
    assert (reason, wamid) == ("dossier_superseded", None)
    async with sessions.begin() as session:
        await session.execute(
            sa.text("UPDATE tenant_guard.dossiers SET statut='valide' WHERE id=:id"),
            {"id": dossier_id},
        )
        await session.execute(
            sa.text(
                "INSERT INTO tenant_guard.dossier_history (id,dossier_id,field_changed,new_value,old_value) VALUES (:id,:dossier,'statut','valide','rejete')"
            ),
            {"id": newer_history_id, "dossier": dossier_id},
        )
        await enqueue_notification(session, tenant_id, newer_history_id, dossier_id, contact_id)
    reason, wamid = await service._send_with_current_consent(
        tenant,
        contact_id,
        template_name="x",
        language_code="fr",
        components=[],
        durable_claim=claim,
        expected_status="valide",
        expected_old_status="en_attente",
    )
    assert (reason, wamid) == ("dossier_superseded", None)
    sender.send_template.assert_awaited_once()
    assert await process_one_notification(tenant, service) == "sent"
    assert sender.send_template.await_count == 2
    async with sessions.begin() as session:
        outcome = (
            await session.execute(
                sa.text(
                    "SELECT state, provider_message_id FROM public.notification_outbox_events WHERE history_id=:id"
                ),
                {"id": newer_history_id},
            )
        ).one()
        assert tuple(outcome) == ("sent", "wamid.accepted")

    # Exercise the actual importer and verify its dossier update and intent commit together.
    sync_id = uuid.uuid4()
    async with sessions.begin() as session:
        await session.execute(
            sa.text("INSERT INTO tenant_guard.sync_logs (id,status) VALUES (:id,'pending')"),
            {"id": sync_id},
        )
    importer = DossierImportService()
    report = await importer.import_dossiers(
        [DossierImportRow(row_number=1, numero="A", statut="rejete")],
        sync_id,
        tenant,
        durable_notifications=True,
    )
    assert report.rows_updated == 1 and report.notifications_enqueued == 1
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT statut FROM tenant_guard.dossiers WHERE id=:id"), {"id": dossier_id}
            )
        ).scalar_one() == "rejete"
        assert (
            await session.execute(
                sa.text(
                    "SELECT count(*) FROM public.notification_outbox_events WHERE tenant_id=:tenant AND dossier_id=:dossier AND state='pending'"
                ),
                {"tenant": tenant_id, "dossier": dossier_id},
            )
        ).scalar_one() == 1

    failure_sync_id = uuid.uuid4()
    async with sessions.begin() as session:
        await session.execute(
            sa.text("INSERT INTO tenant_guard.sync_logs (id,status) VALUES (:id,'pending')"),
            {"id": failure_sync_id},
        )
        await session.execute(
            sa.text(
                "ALTER TABLE public.notification_outbox_events ADD CONSTRAINT test_reject_pending CHECK (state <> 'pending') NOT VALID"
            )
        )
    with pytest.raises(IntegrityError):
        await importer.import_dossiers(
            [DossierImportRow(row_number=1, numero="A", statut="valide")],
            failure_sync_id,
            tenant,
            durable_notifications=True,
        )
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT statut FROM tenant_guard.dossiers WHERE id=:id"), {"id": dossier_id}
            )
        ).scalar_one() == "rejete"
        assert (
            await session.execute(
                sa.text("SELECT count(*) FROM tenant_guard.dossier_history WHERE sync_log_id=:id"),
                {"id": failure_sync_id},
            )
        ).scalar_one() == 0
        assert (
            await session.execute(
                sa.text("SELECT status FROM tenant_guard.sync_logs WHERE id=:id"),
                {"id": failure_sync_id},
            )
        ).scalar_one() == "pending"
    await engine.dispose()
