"""Exercise restricted runtime paths against a disposable copy of the schema."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import update
from sqlalchemy.exc import ProgrammingError

from app.core.config import get_settings
from app.core.database import close_engine, get_session_factory
from app.core.tenant import TenantResolver
from app.core.tenant_lifecycle import protect_ingestion
from app.models.admin import Admin
from app.models.enums import AdminRole, KBDocumentStatus, TenantStatus, UnansweredStatus
from app.models.feedback import UnansweredQuestion
from app.models.kb import KBDocument
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate
from app.services.crypto.kms import KMSService
from app.services.crypto.startup_guard import assert_master_key_consistent
from app.services.tenant.provisioning import TenantProvisioningService
from app.workers.ingestion import recover_stale_ingestions
from app.workers.learning import recover_approved_questions
from app.workers.purge import task_purge_expired_data


class Queue:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))
        return object()


async def main():
    settings = get_settings()
    if (settings.postgres_host, settings.postgres_db, settings.postgres_user) != (
        "codex-db-credential-pg",
        "ragtest_dbcredentials",
        "fixture_runtime",
    ):
        raise RuntimeError("Refusing to run outside the credential fixture")
    factory = get_session_factory()
    service = TenantProvisioningService()
    old = datetime.now(UTC) - timedelta(hours=2)
    tenant_id, admin_id = uuid.uuid4(), uuid.uuid4()
    async with factory() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Fixture existing",
                slug="onssa",
                region="Test",
                status=TenantStatus.active,
            )
        )
        await session.flush()
        session.add(
            Admin(
                id=admin_id,
                email="fixture@example.invalid",
                full_name="Fixture",
                password_hash="fixture",
                role=AdminRole.supervisor,
                tenant_id=tenant_id,
                is_active=True,
            )
        )
        await session.commit()
    tenant = await TenantResolver.from_slug("onssa")
    async with tenant.db_session() as session:
        session.add(
            KBDocument(
                title="Fixture document",
                status=KBDocumentStatus.pending,
                file_path="fixture.txt",
                validated_by=admin_id,
                validated_at=old,
                updated_at=old,
            )
        )
        session.add(
            UnansweredQuestion(
                question="Fixture question",
                proposed_answer="Fixture answer",
                status=UnansweredStatus.approved,
                reviewed_by=admin_id,
                updated_at=old,
            )
        )
    created = await service._create_tenant_record(
        TenantCreate(name="Fixture new", slug="fixture", region="Test")
    )
    await service._create_schema("fixture")
    async with factory() as session:
        await session.execute(
            update(Tenant).where(Tenant.id == created.id).values(status=TenantStatus.active)
        )
        await session.commit()
    kms = KMSService(factory, SimpleNamespace(), "ab" * 32)
    await kms.generate_tenant_key(tenant_id)
    await assert_master_key_consistent(factory, bytes.fromhex("ab" * 32))
    async with protect_ingestion(tenant):
        pass
    queue = Queue()
    assert await recover_stale_ingestions({"redis": queue}) == 1
    assert await recover_approved_questions({"redis": queue}) == 1
    assert len(queue.jobs) == 2
    summary = await task_purge_expired_data({})
    assert summary["tenants_processed"] == 2
    assert summary["tenants_errored"] == 0
    await service._drop_schema("fixture")
    try:
        await service._drop_schema("onssa")
    except ProgrammingError:
        pass
    else:
        raise AssertionError("Runtime login unexpectedly dropped an existing tenant schema")
    await close_engine()
    print("RESTRICTED_RUNTIME_WORKERS_AND_LIFECYCLE_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
