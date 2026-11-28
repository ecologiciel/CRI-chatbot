"""Concurrent use of the singleton must not cross institution boundaries."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.dossier.import_service import DossierImportRow, DossierImportService
from app.services.tenant.provisioning import TenantProvisioningService


@pytest.mark.asyncio
async def test_simultaneous_imports_publish_only_their_own_events(monkeypatch):
    first = TenantContext(uuid.uuid4(), "first", "First", "active", None)
    second = TenantContext(uuid.uuid4(), "second", "Second", "active", None)
    ready = asyncio.Event()
    entered = 0
    published = {}

    @asynccontextmanager
    async def fake_session(_tenant):
        session = AsyncMock()
        session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        yield session

    async def process(batch, sync_id, session, report, pending_notifications):
        nonlocal entered
        pending_notifications.append({"owner": batch[0].numero})
        entered += 1
        if entered == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=3)

    async def publish(tenant, notifications):
        published[tenant.id] = list(notifications)

    monkeypatch.setattr(TenantContext, "db_session", fake_session)
    service = DossierImportService()
    service._process_batch = process
    service._publish_notifications = publish
    monkeypatch.setattr("app.services.dossier.import_service.IMPORT_ROWS", MagicMock())
    monkeypatch.setattr("app.services.dossier.import_service.IMPORT_DURATION", MagicMock())
    await asyncio.gather(
        service.import_dossiers(
            [DossierImportRow(row_number=1, numero="first")], uuid.uuid4(), first
        ),
        service.import_dossiers(
            [DossierImportRow(row_number=1, numero="second")], uuid.uuid4(), second
        ),
    )
    assert published == {first.id: [{"owner": "first"}], second.id: [{"owner": "second"}]}


@pytest.mark.asyncio
async def test_postgres_imports_keep_events_with_their_institution(monkeypatch):
    url = os.getenv("TEST_IMPORT_ISOLATION_DB_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL")
    if not (make_url(url).database or "").startswith("ragtest_"):
        raise RuntimeError("Refusing non-fixture PostgreSQL")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.tenant.get_session_factory", lambda: sessions)
    monkeypatch.setattr("app.services.tenant.provisioning.get_session_factory", lambda: sessions)
    tenants = [
        TenantContext(uuid.uuid4(), "ni" + uuid.uuid4().hex[:16], "Fixture", "active", None)
        for _ in range(2)
    ]
    records = [(uuid.uuid4(), uuid.uuid4(), f"fixture-{i}-{uuid.uuid4().hex}") for i in range(2)]
    try:
        for tenant, (sync_id, dossier_id, numero) in zip(tenants, records, strict=True):
            await TenantProvisioningService()._create_schema(tenant.slug)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        f"INSERT INTO {tenant.db_schema}.sync_logs (id,source_type) VALUES (:id,'csv')"
                    ),
                    {"id": sync_id},
                )
                await conn.execute(
                    text(
                        f"INSERT INTO {tenant.db_schema}.dossiers (id,numero,statut) VALUES (:id,:numero,'rejete')"
                    ),
                    {"id": dossier_id, "numero": numero},
                )
        service = DossierImportService()
        service._publish_notifications = AsyncMock()
        await asyncio.gather(
            *(
                service.import_dossiers(
                    [DossierImportRow(row_number=1, numero=numero, statut="valide")],
                    sync_id,
                    tenant,
                )
                for tenant, (sync_id, _, numero) in zip(tenants, records, strict=True)
            )
        )
        events = {
            call.args[0].id: call.args[1] for call in service._publish_notifications.await_args_list
        }
        assert len(events) == 2
        for tenant, (_, dossier_id, numero) in zip(tenants, records, strict=True):
            assert [(e["dossier_id"], e["numero"]) for e in events[tenant.id]] == [
                (str(dossier_id), numero)
            ]
    finally:
        async with engine.begin() as conn:
            for tenant in tenants:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {tenant.db_schema} CASCADE"))
        await engine.dispose()
