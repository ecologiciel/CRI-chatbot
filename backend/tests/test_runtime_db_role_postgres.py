"""Privilege rehearsal only against an explicitly supplied disposable database."""

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get("TEST_RUNTIME_ROLE_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL database")


@pytest.mark.asyncio
async def test_runtime_role_cannot_mutate_audit_or_schema_version():
    engine = create_async_engine(URL)
    sql = (Path(__file__).parents[2] / "scripts/prepare-runtime-db-role.sql").read_text()
    sql = sql.replace("\\set ON_ERROR_STOP on", "")
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE public.audit_logs (id integer PRIMARY KEY, action text)")
        )
        await conn.execute(
            text("CREATE TABLE public.alembic_version (version_num text PRIMARY KEY)")
        )
        await conn.execute(text("CREATE TABLE public.admins (id integer PRIMARY KEY)"))
        await conn.execute(text("CREATE SCHEMA tenant_template"))
        await conn.execute(text("CREATE TABLE tenant_template.contacts (id integer PRIMARY KEY)"))
        await conn.execute(text("CREATE SCHEMA tenant_existing"))
        await conn.execute(text("CREATE TABLE tenant_existing.contacts (id integer PRIMARY KEY)"))
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(sql)
        await conn.execute(text("SET ROLE cri_runtime_access"))
        await conn.execute(text("INSERT INTO public.audit_logs VALUES (1,'test')"))
        await conn.execute(text("INSERT INTO tenant_existing.contacts VALUES (1)"))
        await conn.execute(text("CREATE SCHEMA tenant_new"))
        await conn.execute(
            text("CREATE TABLE tenant_new.contacts (LIKE tenant_template.contacts INCLUDING ALL)")
        )
        await conn.execute(
            text("CREATE TABLE tenant_new.links (admin_id integer REFERENCES public.admins(id))")
        )
        await conn.commit()
        for statement in [
            "UPDATE public.audit_logs SET action='modified'",
            "DELETE FROM public.audit_logs",
            "TRUNCATE public.audit_logs",
            "INSERT INTO public.alembic_version VALUES ('forged')",
            "DROP SCHEMA tenant_existing CASCADE",
        ]:
            with pytest.raises(DBAPIError):
                await conn.execute(text(statement))
            await conn.rollback()
        await conn.execute(text("DROP SCHEMA tenant_new CASCADE"))
        await conn.commit()
        assert (
            await conn.execute(text("SELECT action FROM public.audit_logs WHERE id=1"))
        ).scalar_one() == "test"
        await conn.execute(text("RESET ROLE"))
        await conn.execute(text("DROP OWNED BY cri_runtime_access"))
        await conn.execute(text("DROP ROLE cri_runtime_access"))
        await conn.commit()
    await engine.dispose()
