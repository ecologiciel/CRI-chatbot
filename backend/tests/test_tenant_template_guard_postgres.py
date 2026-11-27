"""Exercise template drift detection on a disposable copy of the real schema."""

import os
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import TenantProvisioningError
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_TEMPLATE_GUARD_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable schema-only PostgreSQL copy")


@pytest.mark.asyncio
async def test_template_drift_blocks_provisioning_before_schema_creation():
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one().startswith("ragtest_")
        await conn.execute(text("CREATE TABLE tenant_template.unreviewed_table (id integer)"))
    service = TenantProvisioningService()
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
        with pytest.raises(TenantProvisioningError, match="modèle de données"):
            await service._create_schema("guardfixture")
        async with engine.begin() as conn:
            assert (await conn.execute(text("SELECT to_regnamespace('tenant_guardfixture') IS NULL"))).scalar_one()
            await conn.execute(text("DROP TABLE tenant_template.unreviewed_table"))
            await conn.execute(text("ALTER TABLE tenant_template.messages DROP CONSTRAINT messages_conversation_id_fkey"))
        with pytest.raises(TenantProvisioningError, match="relations du modèle"):
            await service._create_schema("guardfixture")
        async with engine.begin() as conn:
            assert (await conn.execute(text("SELECT to_regnamespace('tenant_guardfixture') IS NULL"))).scalar_one()
            await conn.execute(text("ALTER TABLE tenant_template.messages ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES tenant_template.conversations(id) ON DELETE CASCADE"))
        await service._create_schema("guardfixture")
        async with engine.begin() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='tenant_guardfixture' AND c.contype='f'"))).scalar_one()
            assert count == 17
            await conn.execute(text("DROP SCHEMA tenant_guardfixture CASCADE"))
    await engine.dispose()
