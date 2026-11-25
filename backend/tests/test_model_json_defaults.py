"""JSON defaults should work when models are created in PostgreSQL."""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.rag_evaluation import RAGEvaluationCase, RAGEvaluationRun
from app.models.tenant import Tenant


@pytest.mark.asyncio
async def test_json_defaults_in_disposable_database():
    dsn = os.getenv("AUTH_PASSWORD_TEST_DSN")
    if not dsn:
        pytest.skip("Requires isolated auth_password_test PostgreSQL")
    engine = create_async_engine(dsn)
    schema = f"testdefaults_{uuid.uuid4().hex}"
    created = False
    try:
        async with engine.begin() as connection:
            assert (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one() == "auth_password_test"
            await connection.run_sync(lambda conn: Tenant.__table__.create(conn, checkfirst=True))
            tenant_id = uuid.uuid4()
            result = await connection.execute(
                text(
                    "INSERT INTO public.tenants (id, name, slug, region) VALUES (:id, 'Fixture', :slug, 'Fixture') RETURNING public_config = '{}'::jsonb"
                ),
                {"id": tenant_id, "slug": f"fixture{tenant_id.hex}"},
            )
            assert result.scalar_one() is True
            await connection.execute(
                text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id}
            )
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
            created = True
            await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            await connection.run_sync(
                lambda conn: RAGEvaluationCase.__table__.create(conn, checkfirst=True)
            )
            await connection.run_sync(
                lambda conn: RAGEvaluationRun.__table__.create(conn, checkfirst=True)
            )
            result = await connection.execute(
                text(
                    "INSERT INTO rag_evaluation_cases (query) VALUES ('fixture') RETURNING expected_document_ids = '[]'::jsonb"
                )
            )
            assert result.scalar_one() is True
            result = await connection.execute(
                text(
                    "INSERT INTO rag_evaluation_runs DEFAULT VALUES RETURNING metrics = '{}'::jsonb"
                )
            )
            assert result.scalar_one() is True
    finally:
        if created:
            async with engine.begin() as connection:
                await connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()
