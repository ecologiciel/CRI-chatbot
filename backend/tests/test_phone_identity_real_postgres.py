"""Phone identity invariants on disposable tenant schemas."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.contact.import_export import ContactImportExportService
from app.services.contact.segmentation import SegmentationService
from app.services.contact.service import ContactService
from app.services.dossier.service import DossierService
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_WA_ORDER_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_new_tenant_inherits_phone_identity_constraint():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        await TenantProvisioningService()._create_schema("fixture_phone_a")
        await TenantProvisioningService()._create_schema("fixture_phone_b")
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_phone_a.contacts (phone) VALUES ('212600000011'),('web_fixture_a')"))
        await conn.execute(text("INSERT INTO tenant_fixture_phone_b.contacts (phone) VALUES ('+212600000011')"))
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO tenant_fixture_phone_a.contacts (phone) VALUES ('+212600000011')"))
    tenant = TenantContext(uuid.uuid4(), "fixture_phone_a", "Fixture", "active", None)
    audit = AsyncMock()
    with (patch("app.core.tenant.get_session_factory", return_value=factory),
          patch("app.services.audit.service.get_audit_service", return_value=audit)):
        contact = await ContactService().get_or_create(tenant, "+212600000011")
        assert contact.phone == "212600000011"
        assert await SegmentationService().process_stop_command(tenant, "+212600000011")
        async with tenant.db_session() as session:
            dossier_contact = await DossierService._get_contact_by_phone(session, "+212600000011")
            assert dossier_contact and dossier_contact.id == contact.id
        imported = await ContactImportExportService().import_contacts(
            tenant,
            b"phone,name\n+212600000011,Existing\n+212600000012,New\n212600000012,Repeat\n",
            "fixture.csv",
        )
        assert imported.created == 1 and imported.skipped == 2 and not imported.errors
        first, second = await asyncio.gather(
            ContactService().get_or_create(tenant, "+212600000013"),
            ContactService().get_or_create(tenant, "212600000013"),
        )
        assert first.id == second.id
    async with engine.connect() as conn:
        assert (await conn.scalar(text("SELECT count(*) FROM tenant_fixture_phone_a.contacts"))) == 4
        assert (await conn.scalar(text("SELECT count(*) FROM tenant_fixture_phone_b.contacts"))) == 1
        assert (await conn.scalar(text("SELECT opt_in_status::text FROM tenant_fixture_phone_a.contacts WHERE phone='212600000011'"))) == "opted_out"
    await engine.dispose()
