"""Phone identity invariants on disposable tenant schemas."""

import os
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
    async with engine.connect() as conn:
        assert (await conn.scalar(text("SELECT count(*) FROM tenant_fixture_phone_a.contacts"))) == 2
        assert (await conn.scalar(text("SELECT count(*) FROM tenant_fixture_phone_b.contacts"))) == 1
    await engine.dispose()
