"""Stale deletion requests must not target a replacement institution."""
import os
import uuid
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
                await service.deprovision_tenant(slug, tenant_id=old_id)
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
