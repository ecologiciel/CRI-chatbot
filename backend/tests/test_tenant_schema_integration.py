"""Verify new demo schemas against a disposable, migrated PostgreSQL database."""

import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.tenant.provisioning import TenantProvisioningService


@pytest.mark.asyncio
async def test_new_tenant_clones_tables_and_foreign_keys():
    dsn = os.environ.get("RAG_TENANT_TEST_DSN")
    if not dsn:
        pytest.skip("Set RAG_TENANT_TEST_DSN to the disposable onssa_full_migration database")
    engine = create_async_engine(dsn)
    slug = "prospect" + uuid.uuid4().hex[:16]
    schema = "tenant_" + slug
    created = False
    try:
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT current_database()"))
            ).scalar_one() == "onssa_full_migration"
            assert (
                await conn.execute(
                    text("SELECT to_regnamespace(:schema) IS NULL"), {"schema": schema}
                )
            ).scalar_one()
        with patch(
            "app.services.tenant.provisioning.get_session_factory",
            return_value=async_sessionmaker(engine),
        ):
            await TenantProvisioningService()._create_schema(slug)
        created = True
        async with engine.connect() as conn:
            tables = text("SELECT tablename FROM pg_tables WHERE schemaname=:schema")
            template_tables = set(
                (await conn.execute(tables, {"schema": "tenant_template"})).scalars()
            )
            new_tables = set((await conn.execute(tables, {"schema": schema})).scalars())
            assert new_tables == template_tables
            foreign_keys = text("""
                SELECT c.relname, pg_get_constraintdef(f.oid)
                FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=:schema AND f.contype='f'
            """)
            expected = {
                (table, definition.replace("tenant_template.", "tenant_TEST."))
                for table, definition in (
                    await conn.execute(foreign_keys, {"schema": "tenant_template"})
                )
            }
            actual = {
                (table, definition.replace(schema + ".", "tenant_TEST."))
                for table, definition in (await conn.execute(foreign_keys, {"schema": schema}))
            }
            assert actual == expected
    finally:
        async with engine.begin() as conn:
            if (
                created
                and (await conn.execute(text("SELECT current_database()"))).scalar_one()
                == "onssa_full_migration"
            ):
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
