"""Exercise pooled tenant transactions against an explicitly disposable database."""

import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext

URL = os.getenv("TEST_TENANT_POOL_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL database")


@pytest.mark.asyncio
async def test_tenant_search_path_is_transaction_local_and_restored():
    engine = create_async_engine(
        URL,
        pool_size=1,
        max_overflow=0,
        connect_args={"server_settings": {"search_path": "public"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        assert name.startswith("ragtest_")
        await conn.execute(text("CREATE SCHEMA tenant_alpha"))
        await conn.execute(text("CREATE SCHEMA tenant_beta"))
        for schema, value in (("public", "public"), ("tenant_alpha", "alpha"), ("tenant_beta", "beta")):
            await conn.execute(text(f"CREATE TABLE {schema}.pool_probe (value text)"))
            await conn.execute(text(f"INSERT INTO {schema}.pool_probe VALUES (:value)"), {"value": value})
        await conn.execute(text("CREATE TABLE public.pool_public_only (value text)"))
        await conn.execute(text("INSERT INTO public.pool_public_only VALUES ('shared')"))

    alpha = TenantContext(uuid.uuid4(), "alpha", "Alpha", "active", None)
    beta = TenantContext(uuid.uuid4(), "beta", "Beta", "active", None)
    with patch("app.core.tenant.get_session_factory", return_value=factory):
        async with alpha.db_session() as session:
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "alpha"
            assert (await session.execute(text("SELECT value FROM public.pool_public_only"))).scalar_one() == "shared"
            await session.commit()
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "alpha"
            await session.rollback()
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "alpha"

        # A missing tenant table or whole schema must never resolve an
        # unqualified name to a similarly named table in public.
        with pytest.raises(DBAPIError):
            async with alpha.db_session() as session:
                await session.execute(text("SELECT value FROM pool_public_only"))
        missing = TenantContext(uuid.uuid4(), "missing", "Missing", "active", None)
        with pytest.raises(DBAPIError):
            async with missing.db_session() as session:
                await session.execute(text("SELECT value FROM pool_probe"))

        async with factory() as session:
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "public"

        async with beta.db_session() as session:
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "beta"

        async with factory() as session:
            assert (await session.execute(text("SELECT value FROM pool_probe"))).scalar_one() == "public"

    await engine.dispose()
