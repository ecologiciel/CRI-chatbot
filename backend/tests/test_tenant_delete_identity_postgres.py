"""Stale deletion requests must not target a replacement institution."""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import TenantProvisioningError
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_TENANT_DELETE_IDENTITY_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_stale_delete_does_not_deactivate_or_remove_replacement():
    url = make_url(URL)
    if not url.database or not url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing to run outside a disposable ragtest_ database")
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    current_id, old_id = uuid.uuid4(), uuid.uuid4()
    slug = "fixture" + current_id.hex
    service = TenantProvisioningService()
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))) == url.database
            await conn.execute(
                text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Fixture','active')"),
                {"id": current_id, "slug": slug},
            )
        with (
            patch("app.services.tenant.provisioning.get_session_factory", return_value=sessions),
            patch("app.core.tenant_lifecycle.get_session_factory", return_value=sessions),
            patch.object(service, "_empty_and_remove_bucket", new_callable=AsyncMock) as bucket,
            patch.object(service, "_delete_qdrant_collection", new_callable=AsyncMock) as qdrant,
            patch.object(service, "_drop_schema", new_callable=AsyncMock) as schema,
        ):
            with pytest.raises(TenantProvisioningError, match="resources were not removed"):
                await service.deprovision_tenant(slug, tenant_id=old_id, actor_id=uuid.uuid4())
            bucket.assert_not_awaited()
            qdrant.assert_not_awaited()
            schema.assert_not_awaited()
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT id,status::text FROM public.tenants WHERE slug=:slug"), {"slug": slug})).one()
            assert row == (current_id, "active")
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": current_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_deactivation_before_cleanup():
    url = make_url(URL)
    if not url.database or not url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing to run outside a disposable ragtest_ database")
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    slug = "fixture" + tenant_id.hex
    constraint = "fixture_audit_" + tenant_id.hex
    service = TenantProvisioningService()
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))) == url.database
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Fixture','active')"), {"id": tenant_id, "slug": slug})
            await conn.execute(text(f"ALTER TABLE public.audit_logs ADD CONSTRAINT {constraint} CHECK (tenant_slug <> '{slug}') NOT VALID"))
        with (
            patch("app.services.tenant.provisioning.get_session_factory", return_value=sessions),
            patch("app.core.tenant_lifecycle.get_session_factory", return_value=sessions),
            patch.object(service, "_empty_and_remove_bucket", new_callable=AsyncMock) as bucket,
            patch.object(service, "_drop_schema", new_callable=AsyncMock) as schema,
        ):
            with pytest.raises(TenantProvisioningError, match="resources were not removed"):
                await service.deprovision_tenant(slug, tenant_id=tenant_id, actor_id=uuid.uuid4())
            bucket.assert_not_awaited()
            schema.assert_not_awaited()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT status::text FROM public.tenants WHERE id=:id"), {"id": tenant_id}) == "active"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER TABLE public.audit_logs DROP CONSTRAINT IF EXISTS {constraint}"))
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_and_deactivation_are_committed_before_cleanup():
    url = make_url(URL)
    if not url.database or not url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing to run outside a disposable ragtest_ database")
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, actor_id = uuid.uuid4(), uuid.uuid4()
    slug = "fixture" + tenant_id.hex
    service = TenantProvisioningService()
    observed = {}
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))) == url.database
            await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:id,'Fixture',:slug,'Fixture','active')"), {"id": tenant_id, "slug": slug})
        async def check_then_fail(_slug):
            async with engine.connect() as conn:
                observed["status"] = await conn.scalar(text("SELECT status::text FROM public.tenants WHERE id=:id"), {"id": tenant_id})
                observed["audit"] = (await conn.execute(text("SELECT user_id,resource_id FROM public.audit_logs WHERE tenant_slug=:slug AND action='tenant_delete_start'"), {"slug": slug})).one_or_none()
            raise RuntimeError("fixture storage failure")
        with (
            patch("app.services.tenant.provisioning.get_session_factory", return_value=sessions),
            patch("app.core.tenant_lifecycle.get_session_factory", return_value=sessions),
            patch("app.services.tenant.provisioning.get_redis", return_value=AsyncMock()),
            patch("app.services.tenant.provisioning._clear_tenant_redis_keys", new=AsyncMock()),
            patch("app.services.tenant.provisioning.get_settings", return_value=SimpleNamespace(kms_master_key="")),
            patch.object(service, "_empty_and_remove_bucket", side_effect=check_then_fail),
            patch.object(service, "_delete_qdrant_collection", new_callable=AsyncMock),
            patch.object(service, "_drop_schema", new_callable=AsyncMock),
        ):
            with pytest.raises(TenantProvisioningError, match="minio"):
                await service.deprovision_tenant(slug, tenant_id=tenant_id, actor_id=actor_id)
        assert observed == {"status": "inactive", "audit": (actor_id, str(tenant_id))}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM public.audit_logs WHERE tenant_slug=:slug"), {"slug": slug})
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
        await engine.dispose()
