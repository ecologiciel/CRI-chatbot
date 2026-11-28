"""Rehearse separate login privileges with synthetic tenant schemas only."""
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.getenv("TEST_WA_FENCE_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_dedicated_logins_reject_cross_schema_and_unsafe_role_membership():
    elevated = create_async_engine(URL)
    login_a = login_b = None
    audit_sql = (Path(__file__).parents[2] / "scripts/rehearse-audit-tenant-login.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
    async with elevated.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        assert not await conn.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('fixture_iso_a','fixture_iso_b','fixture_iso_extra'))"))
        assert not await conn.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN ('tenant_fixture_iso_a','tenant_fixture_iso_b'))"))
        await conn.execute(text("CREATE SCHEMA tenant_fixture_iso_a"))
        await conn.execute(text("CREATE SCHEMA tenant_fixture_iso_b"))
        await conn.execute(text("CREATE TABLE tenant_fixture_iso_a.contacts (value text NOT NULL)"))
        await conn.execute(text("CREATE TABLE tenant_fixture_iso_b.contacts (value text NOT NULL)"))
        await conn.execute(text("INSERT INTO tenant_fixture_iso_a.contacts VALUES ('fixture-a')"))
        await conn.execute(text("INSERT INTO tenant_fixture_iso_b.contacts VALUES ('fixture-b')"))
        await conn.execute(text("CREATE ROLE fixture_iso_a LOGIN PASSWORD 'synthetic-fixture-password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"))
        await conn.execute(text("CREATE ROLE fixture_iso_b LOGIN PASSWORD 'synthetic-fixture-password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"))
        await conn.execute(text("GRANT USAGE ON SCHEMA tenant_fixture_iso_a TO fixture_iso_a"))
        await conn.execute(text("GRANT USAGE ON SCHEMA tenant_fixture_iso_b TO fixture_iso_b"))
        await conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_fixture_iso_a.contacts TO fixture_iso_a"))
        await conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_fixture_iso_b.contacts TO fixture_iso_b"))
    login_a = create_async_engine(make_url(URL).set(username="fixture_iso_a", password="synthetic-fixture-password"))
    login_b = create_async_engine(make_url(URL).set(username="fixture_iso_b", password="synthetic-fixture-password"))

    async def audit(engine, schema):
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('rehearsal.expected_tenant_schema', :schema, true)"), {"schema": schema})
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(audit_sql)

    try:
        await audit(login_a, "tenant_fixture_iso_a")
        await audit(login_b, "tenant_fixture_iso_b")
        for engine, own, other, expected in (
            (login_a, "tenant_fixture_iso_a", "tenant_fixture_iso_b", "fixture-a"),
            (login_b, "tenant_fixture_iso_b", "tenant_fixture_iso_a", "fixture-b"),
        ):
            async with engine.connect() as conn:
                assert (await conn.scalar(text(f"SELECT value FROM {own}.contacts"))) == expected
            for statement in (f"SELECT * FROM {other}.contacts", f"INSERT INTO {other}.contacts VALUES ('forbidden')"):
                with pytest.raises(DBAPIError):
                    async with engine.begin() as conn:
                        await conn.execute(text(statement))
        async with elevated.begin() as conn:
            await conn.execute(text("CREATE ROLE fixture_iso_extra NOLOGIN"))
            await conn.execute(text("GRANT USAGE ON SCHEMA tenant_fixture_iso_b TO fixture_iso_extra"))
            await conn.execute(text("GRANT SELECT ON tenant_fixture_iso_b.contacts TO fixture_iso_extra"))
            await conn.execute(text("GRANT fixture_iso_extra TO fixture_iso_a WITH INHERIT FALSE"))
        with pytest.raises(asyncpg.PostgresError, match="another tenant schema"):
            await audit(login_a, "tenant_fixture_iso_a")
        async with login_a.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE fixture_iso_extra"))
            assert (await conn.scalar(text("SELECT value FROM tenant_fixture_iso_b.contacts"))) == "fixture-b"
    finally:
        await login_a.dispose()
        await login_b.dispose()
        async with elevated.begin() as conn:
            await conn.execute(text("DROP SCHEMA tenant_fixture_iso_a CASCADE"))
            await conn.execute(text("DROP SCHEMA tenant_fixture_iso_b CASCADE"))
            for role in ("fixture_iso_a", "fixture_iso_b", "fixture_iso_extra"):
                exists = await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role})
                if exists:
                    await conn.execute(text(f"DROP OWNED BY {role}"))
                    await conn.execute(text(f"DROP ROLE {role}"))
        await elevated.dispose()
