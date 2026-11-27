"""Exercise the real row locks on a separate disposable PostgreSQL database."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.api.v1.dossiers import (
    DossierImportReview,
    get_import_request,
    list_import_requests,
    review_import_request,
)
from app.api.v1.dossiers import import_dossiers as accept_import
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.dossier import Dossier, DossierHistory
from app.models.sync import SyncConfig, SyncLog
from app.models.tenant import Tenant
from app.services.dossier.import_execution import process_one_durable_import
from app.services.dossier.import_requests import (
    LostImportLeaseError,
    block_watched_retry,
    claim_import,
    register_import,
)
from app.services.dossier.import_retention import purge_one_import_source
from app.services.dossier.import_service import DossierImportRow, DossierImportService
from app.services.notification.outbox import claim_notification, enqueue_notification
from app.services.notification.outbox_execution import process_one_notification
from app.services.notification.service import NotificationService
from app.workers.import_dossier import poll_durable_imports

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
        (Admin, "public"),
        (AuditLog, "public"),
        (Dossier, "tenant_guard"),
        (DossierHistory, "tenant_guard"),
        (Contact, "tenant_guard"),
        (SyncLog, "tenant_guard"),
        (SyncConfig, "tenant_guard"),
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
    request_path = (
        Path(__file__).parents[1] / "alembic/versions/2026_11_27_0021_dossier_import_requests.py"
    )
    request_spec = importlib.util.spec_from_file_location("import_migration", request_path)
    request_migration = importlib.util.module_from_spec(request_spec)
    request_spec.loader.exec_module(request_migration)

    def install(connection):
        metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            request_migration.upgrade()

    tenant_id, dossier_id, contact_id, history_id = (uuid.uuid4() for _ in range(4))
    config = {"phone_number_id": "123", "access_token": "test"}
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA tenant_guard"))
        await conn.run_sync(install)
        await conn.execute(
            sa.text(
                "INSERT INTO public.tenants (id,slug,status,whatsapp_config) VALUES (:id,'guard','active',CAST(:cfg AS jsonb))"
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
        id=tenant_id,
        slug="guard",
        whatsapp_config=config,
        db_session=db_session,
        minio_bucket="cri-guard",
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
    request_id = uuid.uuid4()
    async with sessions.begin() as session:
        await session.execute(
            sa.text("INSERT INTO tenant_guard.sync_logs (id,status) VALUES (:id,'pending')"),
            {"id": sync_id},
        )
        await register_import(
            session,
            request_id=request_id,
            tenant_id=tenant_id,
            object_key=f"imports/requests/{request_id.hex}/source.csv",
            content_sha256="a" * 64,
            sync_config_id=None,
            requested_by=None,
        )
        import_claim = await claim_import(session, tenant_id)
    importer = DossierImportService()
    report = await importer.import_dossiers(
        [DossierImportRow(row_number=1, numero="A", statut="rejete")],
        sync_id,
        tenant,
        durable_notifications=True,
        durable_claim=import_claim,
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
        assert (
            await session.execute(
                sa.text(
                    "SELECT state,sync_log_id FROM public.dossier_import_requests WHERE id=:id"
                ),
                {"id": request_id},
            )
        ).one() == ("completed", sync_id)

    failure_sync_id = uuid.uuid4()
    failure_request_id = uuid.uuid4()
    async with sessions.begin() as session:
        await session.execute(
            sa.text("INSERT INTO tenant_guard.sync_logs (id,status) VALUES (:id,'pending')"),
            {"id": failure_sync_id},
        )
        await register_import(
            session,
            request_id=failure_request_id,
            tenant_id=tenant_id,
            object_key=f"imports/requests/{failure_request_id.hex}/source.csv",
            content_sha256="b" * 64,
            sync_config_id=None,
            requested_by=None,
        )
        failed_claim = await claim_import(session, tenant_id)
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
            durable_claim=failed_claim,
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
        assert (
            await session.execute(
                sa.text("SELECT state FROM public.dossier_import_requests WHERE id=:id"),
                {"id": failure_request_id},
            )
        ).scalar_one() == "processing"
        await session.execute(
            sa.text(
                "ALTER TABLE public.notification_outbox_events DROP CONSTRAINT test_reject_pending"
            )
        )
        await session.execute(
            sa.text(
                "UPDATE public.dossier_import_requests SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": failure_request_id},
        )
    with pytest.raises(LostImportLeaseError):
        await importer.import_dossiers(
            [DossierImportRow(row_number=1, numero="A", statut="valide")],
            failure_sync_id,
            tenant,
            durable_notifications=True,
            durable_claim=failed_claim,
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
    # Real importer and database, with only object storage simulated.
    csv_bytes = b"numero,statut\nA,valide\n"
    worker_request = uuid.uuid4()
    async with sessions.begin() as session:
        await register_import(
            session,
            request_id=worker_request,
            tenant_id=tenant_id,
            object_key=f"imports/requests/{worker_request.hex}/source.csv",
            content_sha256=hashlib.sha256(csv_bytes).hexdigest(),
            sync_config_id=None,
            requested_by=None,
        )
    with (
        patch("app.core.tenant.TenantResolver.from_slug", new=AsyncMock(return_value=tenant)),
        patch("app.core.minio.get_object_bytes", new=AsyncMock(return_value=csv_bytes)),
        patch("app.workers.import_dossier.get_settings") as settings,
    ):
        settings.return_value.dossier_notification_outbox_enabled = True
        assert await process_one_durable_import(tenant) == "completed"
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT state FROM public.dossier_import_requests WHERE id=:id"),
                {"id": worker_request},
            )
        ).scalar_one() == "completed"
        assert (
            await session.execute(
                sa.text("SELECT statut FROM tenant_guard.dossiers WHERE id=:id"), {"id": dossier_id}
            )
        ).scalar_one() == "valide"
    corrupted_request = uuid.uuid4()
    async with sessions.begin() as session:
        await register_import(
            session,
            request_id=corrupted_request,
            tenant_id=tenant_id,
            object_key=f"imports/requests/{corrupted_request.hex}/source.csv",
            content_sha256="0" * 64,
            sync_config_id=None,
            requested_by=None,
        )
    with (
        patch("app.core.tenant.TenantResolver.from_slug", new=AsyncMock(return_value=tenant)),
        patch("app.core.minio.get_object_bytes", new=AsyncMock(return_value=csv_bytes)),
        patch("app.workers.import_dossier.get_settings") as settings,
    ):
        settings.return_value.dossier_notification_outbox_enabled = True
        assert await process_one_durable_import(tenant) == "already_finalized_or_lease_lost"
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT state FROM public.dossier_import_requests WHERE id=:id"),
                {"id": corrupted_request},
            )
        ).scalar_one() == "uncertain"
        assert (
            await session.execute(
                sa.text("SELECT statut FROM tenant_guard.dossiers WHERE id=:id"), {"id": dossier_id}
            )
        ).scalar_one() == "valide"
    # Acceptance, deduplication and polling use PostgreSQL as the authority.
    api_bytes = b"numero,statut\nA,rejete\n"
    stored = {}

    async def put_object(*, bucket_name, object_name, data, length, content_type):
        stored[object_name] = data.read()
        assert len(stored[object_name]) == length

    async def fetch_object(bucket, key, *, max_bytes):
        assert bucket == tenant.minio_bucket and len(stored[key]) <= max_bytes
        return stored[key]

    storage = SimpleNamespace(put_object=AsyncMock(side_effect=put_object))
    queue = SimpleNamespace(exists=AsyncMock(return_value=1), enqueue_job=AsyncMock())
    settings = SimpleNamespace(
        dossier_import_worker_enabled=True,
        dossier_durable_imports_enabled=True,
        dossier_notification_outbox_enabled=True,
    )
    admin = SimpleNamespace(sub=str(uuid.uuid4()))
    with (
        patch("app.api.v1.dossiers.get_settings", return_value=settings),
        patch("app.api.v1.dossiers.get_minio", return_value=storage),
        patch("app.api.v1.dossiers.get_arq_pool", return_value=queue),
        patch("app.workers.import_dossier.get_settings", return_value=settings),
        patch("app.core.tenant.TenantResolver.from_slug", new=AsyncMock(return_value=tenant)),
        patch("app.core.database.get_session_factory", return_value=sessions),
        patch("app.core.minio.get_object_bytes", new=AsyncMock(side_effect=fetch_object)),
    ):
        first = await accept_import(
            UploadFile(filename="dossiers.csv", file=io.BytesIO(api_bytes)),
            sync_config_id=None,
            tenant=tenant,
            admin=admin,
        )
        duplicate = await accept_import(
            UploadFile(filename="dossiers.csv", file=io.BytesIO(api_bytes)),
            sync_config_id=None,
            tenant=tenant,
            admin=admin,
        )
        assert first["deduplicated"] is False and duplicate["deduplicated"] is True
        assert first["request_id"] == duplicate["request_id"]
        storage.put_object.assert_awaited_once()
        queue.enqueue_job.assert_not_awaited()
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT count(*) FROM public.audit_logs WHERE action='dossier_import_req'"
                    )
                )
            ).scalar_one() == 2
            await session.execute(
                sa.text(
                    "ALTER TABLE public.audit_logs ADD CONSTRAINT test_reject_import_audit CHECK (action <> 'dossier_import_req') NOT VALID"
                )
            )
        rejected_bytes = b"numero,statut\nA,en_attente\n"
        with pytest.raises(IntegrityError):
            await accept_import(
                UploadFile(filename="dossiers.csv", file=io.BytesIO(rejected_bytes)),
                sync_config_id=None,
                tenant=tenant,
                admin=admin,
            )
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT count(*) FROM public.dossier_import_requests WHERE content_sha256=:hash"
                    ),
                    {"hash": hashlib.sha256(rejected_bytes).hexdigest()},
                )
            ).scalar_one() == 0
            await session.execute(
                sa.text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_reject_import_audit")
            )
        assert await poll_durable_imports({}) == "completed"
        status = await get_import_request(
            uuid.UUID(first["request_id"]), tenant=tenant, _admin=admin
        )
        assert status["state"] == "completed" and status["sync_log_id"] is not None
        config_id = uuid.uuid4()
        async with sessions.begin() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO tenant_guard.sync_configs (id, is_active, column_mapping) "
                    "VALUES (:id, true, CAST(:mapping AS jsonb))"
                ),
                {"id": config_id, "mapping": '{"numero":"numero","statut":"statut"}'},
            )
        changed = await accept_import(
            UploadFile(filename="changed.csv", file=io.BytesIO(b"numero,statut\nA,valide\n\n")),
            sync_config_id=config_id,
            tenant=tenant,
            admin=admin,
        )
        async with sessions.begin() as session:
            await session.execute(
                sa.text(
                    "UPDATE tenant_guard.sync_configs SET column_mapping=CAST(:mapping AS jsonb) WHERE id=:id"
                ),
                {"id": config_id, "mapping": '{"numero":"statut","statut":"numero"}'},
            )
        assert await poll_durable_imports({}) == "already_finalized_or_lease_lost"
        changed_status = await get_import_request(
            uuid.UUID(changed["request_id"]), tenant=tenant, _admin=admin
        )
        assert changed_status["state"] == "uncertain"
        assert changed_status["outcome_code"] == "configuration_changed"
        other_tenant_id, other_request_id = uuid.uuid4(), uuid.uuid4()
        async with sessions.begin() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO public.tenants (id, slug, status) VALUES (:id, 'other', 'active')"
                ),
                {"id": other_tenant_id},
            )
            await register_import(
                session,
                request_id=other_request_id,
                tenant_id=other_tenant_id,
                object_key=f"imports/requests/{other_request_id.hex}/source.csv",
                content_sha256="e" * 64,
                sync_config_id=None,
                requested_by=None,
            )
            await session.execute(
                sa.text("UPDATE public.dossier_import_requests SET state='uncertain' WHERE id=:id"),
                {"id": other_request_id},
            )
        entries = await list_import_requests(
            state="uncertain", limit=1, offset=0, tenant=tenant, _admin=admin
        )
        assert entries["available"] and entries["active"]
        assert len(entries["items"]) == 1 and entries["has_more"]
        assert all(entry["request_id"] != str(other_request_id) for entry in entries["items"])
        assert set(entries["items"][0]) == {
            "request_id",
            "state",
            "outcome_code",
            "review_state",
            "review_outcome",
            "retry_authorized",
            "sync_log_id",
            "created_at",
            "updated_at",
        }
        other_tenant = SimpleNamespace(id=other_tenant_id, db_session=tenant.db_session)
        other_entries = await list_import_requests(
            state="uncertain", limit=25, offset=0, tenant=other_tenant, _admin=admin
        )
        assert [entry["request_id"] for entry in other_entries["items"]] == [str(other_request_id)]
        changed_id = uuid.UUID(changed["request_id"])
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as foreign:
            await review_import_request(
                changed_id,
                DossierImportReview(action="follow_up"),
                tenant=other_tenant,
                admin=admin,
            )
        assert foreign.value.status_code == 404
        async with sessions.begin() as session:
            await session.execute(
                sa.text(
                    "ALTER TABLE public.audit_logs ADD CONSTRAINT test_reject_review CHECK (action <> 'dossier_imp_review') NOT VALID"
                )
            )
        with pytest.raises(IntegrityError):
            await review_import_request(
                changed_id, DossierImportReview(action="follow_up"), tenant=tenant, admin=admin
            )
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text("SELECT review_state FROM public.dossier_import_requests WHERE id=:id"),
                    {"id": changed_id},
                )
            ).scalar_one() == "open"
            await session.execute(
                sa.text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_reject_review")
            )
        follow_up = await review_import_request(
            changed_id, DossierImportReview(action="follow_up"), tenant=tenant, admin=admin
        )
        assert follow_up["review_state"] == "follow_up" and follow_up["state"] == "uncertain"
        closed = await review_import_request(
            changed_id, DossierImportReview(action="close_not_applied"), tenant=tenant, admin=admin
        )
        assert closed["review_state"] == "closed" and closed["review_outcome"] == "not_applied"
        with pytest.raises(HTTPException) as repeat:
            await review_import_request(
                changed_id, DossierImportReview(action="close_applied"), tenant=tenant, admin=admin
            )
        assert repeat.value.status_code == 409
        async with sessions.begin() as session:
            await session.execute(
                sa.text(
                    "ALTER TABLE public.audit_logs ADD CONSTRAINT test_reject_retry CHECK (action <> 'dossier_imp_review') NOT VALID"
                )
            )
        with pytest.raises(IntegrityError):
            await review_import_request(
                changed_id,
                DossierImportReview(action="authorize_retry"),
                tenant=tenant,
                admin=admin,
            )
        async with sessions.begin() as session:
            assert not (
                await session.execute(
                    sa.text(
                        "SELECT retry_authorized FROM public.dossier_import_requests WHERE id=:id"
                    ),
                    {"id": changed_id},
                )
            ).scalar_one()
            await session.execute(
                sa.text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_reject_retry")
            )
        async with sessions.begin() as session:
            content_hash = hashlib.sha256(b"numero,statut\nA,valide\n\n").hexdigest()
            assert await block_watched_retry(session, tenant_id, content_hash)
            retry_task = asyncio.create_task(
                review_import_request(
                    changed_id,
                    DossierImportReview(action="authorize_retry"),
                    tenant=tenant,
                    admin=admin,
                )
            )
            await asyncio.sleep(0.1)
            assert not retry_task.done()
        retry = await asyncio.wait_for(retry_task, 5)
        assert retry["retry_authorized"] is True and retry["state"] == "uncertain"
        with pytest.raises(HTTPException) as repeated_retry:
            await review_import_request(
                changed_id,
                DossierImportReview(action="authorize_retry"),
                tenant=tenant,
                admin=admin,
            )
        assert repeated_retry.value.status_code == 409
        async with sessions.begin() as session:
            assert await block_watched_retry(session, tenant_id, content_hash)
        new_attempt = await accept_import(
            UploadFile(filename="changed.csv", file=io.BytesIO(b"numero,statut\nA,valide\n\n")),
            sync_config_id=config_id,
            tenant=tenant,
            admin=admin,
        )
        assert (
            new_attempt["deduplicated"] is False
            and new_attempt["request_id"] != changed["request_id"]
        )
        second_attempt = await accept_import(
            UploadFile(filename="changed.csv", file=io.BytesIO(b"numero,statut\nA,valide\n\n")),
            sync_config_id=config_id,
            tenant=tenant,
            admin=admin,
        )
        assert (
            second_attempt["deduplicated"] is True
            and second_attempt["request_id"] == new_attempt["request_id"]
        )
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT count(*) FROM public.audit_logs WHERE action='dossier_imp_review' AND resource_id=:id"
                    ),
                    {"id": str(changed_id)},
                )
            ).scalar_one() == 3
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT statut FROM tenant_guard.dossiers WHERE id=:id"), {"id": dossier_id}
            )
        ).scalar_one() == "rejete"
    old_request = uuid.uuid4()
    old_key = f"imports/requests/{old_request.hex}/source.csv"
    async with sessions.begin() as session:
        await register_import(
            session,
            request_id=old_request,
            tenant_id=tenant_id,
            object_key=old_key,
            content_sha256="f" * 64,
            sync_config_id=None,
            requested_by=None,
        )
        await session.execute(
            sa.text(
                "UPDATE public.dossier_import_requests SET state='completed', updated_at=now()-interval '10 days' WHERE id=:id"
            ),
            {"id": old_request},
        )
        await session.execute(
            sa.text(
                "UPDATE public.dossier_import_requests SET updated_at=now()-interval '30 days' WHERE id IN (:pending, :uncertain)"
            ),
            {"pending": uuid.UUID(new_attempt["request_id"]), "uncertain": changed_id},
        )
        await session.execute(
            sa.text(
                "ALTER TABLE public.audit_logs ADD CONSTRAINT test_purge_intent CHECK (action <> 'import_purge_intent') NOT VALID"
            )
        )
    storage = SimpleNamespace(remove_object=AsyncMock())
    with patch("app.services.dossier.import_retention.get_session_factory", return_value=sessions):
        with pytest.raises(IntegrityError):
            await purge_one_import_source(tenant_id, "guard", 5, storage)
        storage.remove_object.assert_not_awaited()
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT source_purge_state FROM public.dossier_import_requests WHERE id=:id"
                    ),
                    {"id": old_request},
                )
            ).scalar_one() == "present"
            await session.execute(
                sa.text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_purge_intent")
            )
        storage.remove_object.side_effect = RuntimeError("storage unavailable")
        with pytest.raises(RuntimeError):
            await purge_one_import_source(tenant_id, "guard", 5, storage)
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT source_purge_state FROM public.dossier_import_requests WHERE id=:id"
                    ),
                    {"id": old_request},
                )
            ).scalar_one() == "deleting"
            await session.execute(
                sa.text(
                    "ALTER TABLE public.audit_logs ADD CONSTRAINT test_purge_done CHECK (action <> 'import_purge_done') NOT VALID"
                )
            )
        storage.remove_object.side_effect = None
        with pytest.raises(IntegrityError):
            await purge_one_import_source(tenant_id, "guard", 5, storage)
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text(
                        "SELECT source_purge_state FROM public.dossier_import_requests WHERE id=:id"
                    ),
                    {"id": old_request},
                )
            ).scalar_one() == "deleting"
            await session.execute(
                sa.text("ALTER TABLE public.audit_logs DROP CONSTRAINT test_purge_done")
            )
        assert await purge_one_import_source(tenant_id, "guard", 5, storage) == "deleted"
        assert await purge_one_import_source(tenant_id, "guard", 5, storage) == "empty"
        assert storage.remove_object.await_args.args == ("cri-guard", old_key)
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text(
                    "SELECT count(*) FROM public.audit_logs WHERE resource_id=:id AND action IN ('import_purge_intent','import_purge_done')"
                ),
                {"id": str(old_request)},
            )
        ).scalar_one() == 2
    await engine.dispose()
