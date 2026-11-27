"""Verify failed tenant provisioning deactivation in a disposable database."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import TenantProvisioningError
from app.models.admin import Admin
from app.models.tenant import Tenant
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.environ.get("TEST_TENANT_PROVISION_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires a disposable PostgreSQL database")


@pytest.mark.asyncio
async def test_deactivation_and_account_revocation_commit_or_roll_back_together():
    engine = create_async_engine(URL)
    metadata = sa.MetaData()
    for model in (Tenant, Admin):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name, col.type, primary_key=col.primary_key, nullable=not col.primary_key
                )
                for col in model.__table__.columns
            ],
            schema="public",
        )
    tenant_id, admin_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.execute(
            sa.text(
                "INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture','fixture','Fixture','active')"
            ),
            {"id": tenant_id},
        )
        await conn.execute(
            sa.text("INSERT INTO public.admins (id,tenant_id,is_active) VALUES (:id,:tenant,true)"),
            {"id": admin_id, "tenant": tenant_id},
        )
        await conn.execute(
            sa.text(
                "ALTER TABLE public.admins ADD CONSTRAINT reject_revocation CHECK (is_active IS TRUE) NOT VALID"
            )
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = TenantProvisioningService()
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=sessions):
        with pytest.raises(IntegrityError):
            await service._deactivate_failed_provisioning(tenant_id, "fixture")
        async with sessions.begin() as session:
            assert (
                await session.execute(
                    sa.text("SELECT status FROM public.tenants WHERE id=:id"), {"id": tenant_id}
                )
            ).scalar_one() == "active"
            assert (
                await session.execute(
                    sa.text("SELECT is_active FROM public.admins WHERE id=:id"), {"id": admin_id}
                )
            ).scalar_one() is True
            await session.execute(
                sa.text("ALTER TABLE public.admins DROP CONSTRAINT reject_revocation")
            )
        await service._deactivate_failed_provisioning(tenant_id, "fixture")
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT status FROM public.tenants WHERE id=:id"), {"id": tenant_id}
            )
        ).scalar_one() == "inactive"
        assert (
            await session.execute(
                sa.text("SELECT is_active FROM public.admins WHERE id=:id"), {"id": admin_id}
            )
        ).scalar_one() is False
        await session.execute(
            sa.text("UPDATE public.tenants SET status='active' WHERE id=:id"), {"id": tenant_id}
        )
        await session.execute(
            sa.text("UPDATE public.admins SET is_active=true WHERE id=:id"), {"id": admin_id}
        )
    with (
        patch("app.services.tenant.provisioning.get_session_factory", return_value=sessions),
        patch("app.core.tenant_lifecycle.get_session_factory", return_value=sessions),
        patch.object(
            service,
            "_create_tenant_record",
            new=AsyncMock(return_value=SimpleNamespace(id=tenant_id)),
        ),
        patch.object(service, "_create_schema", new=AsyncMock()),
        patch.object(
            service,
            "_create_qdrant_collection",
            new=AsyncMock(side_effect=RuntimeError("synthetic failure")),
        ),
        patch.object(service, "_drop_schema", new=AsyncMock()) as drop,
    ):
        async with sessions.begin() as held:
            await held.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock_shared(hashtextextended('tenant-lifecycle:fixture', 0))"
                )
            )
            with pytest.raises(TenantProvisioningError) as error:
                await service.provision_tenant(SimpleNamespace(slug="fixture"))
            assert error.value.details["cleanup_failures"] == ["lifecycle_lock"]
            drop.assert_not_awaited()
    async with sessions.begin() as session:
        assert (
            await session.execute(
                sa.text("SELECT status FROM public.tenants WHERE id=:id"), {"id": tenant_id}
            )
        ).scalar_one() == "inactive"
        assert (
            await session.execute(
                sa.text("SELECT is_active FROM public.admins WHERE id=:id"), {"id": admin_id}
            )
        ).scalar_one() is False
    await engine.dispose()
