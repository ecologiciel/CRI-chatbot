"""Run against a fresh disposable PostgreSQL database supplied explicitly."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.services.dossier.import_requests import (
    ImportConfigurationConflictError,
    LostImportLeaseError,
    claim_import,
    finish_import,
    quarantine_expired_imports,
    register_import,
)

URL = os.environ.get("TEST_DURABLE_IMPORT_DB_URL")
pytestmark = pytest.mark.skipif(
    not URL, reason="requires a dedicated disposable PostgreSQL database"
)


@pytest.mark.asyncio()
async def test_durable_request_transaction_fencing_and_tenant_isolation():
    engine = create_async_engine(URL)
    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/2026_11_27_0021_dossier_import_requests.py"
    )
    spec = importlib.util.spec_from_file_location("durable_import_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def install(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE public.tenants (id uuid PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE public.test_import_writes (id uuid PRIMARY KEY)"))
        await conn.run_sync(install)
        await conn.execute(
            text("INSERT INTO public.tenants VALUES (:a),(:b)"), {"a": tenant_a, "b": tenant_b}
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    request_a, request_b = uuid.uuid4(), uuid.uuid4()
    async with sessions.begin() as session:
        for request_id, tenant in [(request_a, tenant_a), (request_b, tenant_b)]:
            await register_import(
                session,
                request_id=request_id,
                tenant_id=tenant,
                object_key=f"imports/requests/{request_id.hex}/source.csv",
                content_sha256="a" * 64,
                sync_config_id=None,
                requested_by=None,
            )

    held, release = asyncio.Event(), asyncio.Event()

    async def first():
        async with sessions.begin() as session:
            claim = await claim_import(session, tenant_a)
            held.set()
            await release.wait()
            return claim

    task = asyncio.create_task(first())
    await asyncio.wait_for(held.wait(), 5)
    async with sessions.begin() as session:
        assert await claim_import(session, tenant_a) is None
        other = await claim_import(session, tenant_b)
    release.set()
    claim = await task
    assert claim.request_id == request_a and other.request_id == request_b

    with pytest.raises(LostImportLeaseError):
        async with sessions.begin() as session:
            await finish_import(
                session,
                replace(claim, tenant_id=tenant_b),
                state="completed",
                outcome_code="imported",
                sync_log_id=uuid.uuid4(),
            )
    with pytest.raises(LostImportLeaseError):
        async with sessions.begin() as session:
            await finish_import(
                session,
                replace(claim, token=uuid.uuid4()),
                state="completed",
                outcome_code="imported",
                sync_log_id=uuid.uuid4(),
            )
    with pytest.raises(LostImportLeaseError):
        async with sessions.begin() as session:
            await finish_import(
                session,
                replace(claim, content_sha256="b" * 64),
                state="completed",
                outcome_code="imported",
                sync_log_id=uuid.uuid4(),
            )

    write_id = uuid.uuid4()
    async with sessions.begin() as session:
        await session.execute(
            text("INSERT INTO public.test_import_writes VALUES (:id)"), {"id": write_id}
        )
        await finish_import(
            session, claim, state="completed", outcome_code="imported", sync_log_id=uuid.uuid4()
        )
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM public.test_import_writes WHERE id=:id"),
                {"id": write_id},
            )
        ).scalar_one() == 1
        await session.execute(
            text(
                "UPDATE public.dossier_import_requests SET lease_until=now()-interval '1 second' WHERE id=:id"
            ),
            {"id": request_b},
        )
    rolled_back = uuid.uuid4()
    with pytest.raises(LostImportLeaseError):
        async with sessions.begin() as session:
            await session.execute(
                text("INSERT INTO public.test_import_writes VALUES (:id)"), {"id": rolled_back}
            )
            await finish_import(
                session, other, state="completed", outcome_code="imported", sync_log_id=uuid.uuid4()
            )
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM public.test_import_writes WHERE id=:id"),
                {"id": rolled_back},
            )
        ).scalar_one() == 0
        assert await quarantine_expired_imports(session, tenant_a) == 0
        assert await quarantine_expired_imports(session, tenant_b) == 1
        assert await claim_import(session, tenant_b) is None
        assert (
            await session.execute(
                text("SELECT state FROM public.dossier_import_requests WHERE id=:id"),
                {"id": request_b},
            )
        ).scalar_one() == "uncertain"

    # Concurrent submissions of identical content/config produce one request.
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    registered, finish_registration = asyncio.Event(), asyncio.Event()

    async def submit(request_id, wait_for_release):
        async with sessions.begin() as session:
            result = await register_import(
                session,
                request_id=request_id,
                tenant_id=tenant_a,
                object_key=f"imports/requests/{request_id.hex}/source.csv",
                content_sha256="c" * 64,
                sync_config_id=None,
                requested_by=None,
            )
            if wait_for_release:
                registered.set()
                await finish_registration.wait()
            return result

    first_task = asyncio.create_task(submit(first_id, True))
    await asyncio.wait_for(registered.wait(), 5)
    second_task = asyncio.create_task(submit(second_id, False))
    await asyncio.sleep(0.1)
    assert not second_task.done()
    finish_registration.set()
    assert await first_task == (first_id, True)
    assert await second_task == (first_id, False)
    different_config_id = uuid.uuid4()
    conflict_id = uuid.uuid4()
    with pytest.raises(ImportConfigurationConflictError):
        async with sessions.begin() as session:
            await register_import(
                session,
                request_id=conflict_id,
                tenant_id=tenant_a,
                object_key=f"imports/requests/{conflict_id.hex}/source.csv",
                content_sha256="c" * 64,
                sync_config_id=different_config_id,
                requested_by=None,
            )
    async with sessions.begin() as session:
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM public.dossier_import_requests WHERE tenant_id=:tenant AND content_sha256=:hash"
                ),
                {"tenant": tenant_a, "hash": "c" * 64},
            )
        ).scalar_one() == 1
    await engine.dispose()
