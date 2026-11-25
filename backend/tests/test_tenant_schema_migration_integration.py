"""Exercise additive migration on a disposable, migrated PostgreSQL database."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_legacy_tenant_keeps_documents_and_gains_missing_tables():
    dsn = os.environ.get("RAG_ADDITIVE_TEST_DSN")
    if not dsn:
        pytest.skip("Set RAG_ADDITIVE_TEST_DSN to disposable onssa_full_migration")
    engine = sa.create_engine(dsn)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(sa.text("SELECT current_database()")).scalar_one()
                == "onssa_full_migration"
            )
            assert (
                connection.execute(sa.text("SELECT count(*) FROM public.tenants")).scalar_one() == 0
            )
            schema = "tenant_prospect" + uuid.uuid4().hex[:12]
            slug = schema.removeprefix("tenant_")
            connection.execute(
                sa.text(
                    "INSERT INTO public.tenants (name,slug,region,status) VALUES ('Test',:slug,'National','active')"
                ),
                {"slug": slug},
            )
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            legacy_tables = (
                "contacts",
                "kb_documents",
                "incentive_categories",
                "conversations",
                "messages",
                "kb_chunks",
                "incentive_items",
                "feedback",
                "unanswered_questions",
            )
            for table in legacy_tables:
                connection.execute(
                    sa.text(
                        f'CREATE TABLE "{schema}"."{table}" (LIKE tenant_template."{table}" INCLUDING ALL)'
                    )
                )
            document_id = uuid.uuid4()
            connection.execute(
                sa.text(
                    f"INSERT INTO \"{schema}\".kb_documents (id,title,status,chunk_count,active_index_version) VALUES (:id,'Ancien document','indexed',1,1)"
                ),
                {"id": document_id},
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO \"{schema}\".kb_chunks (document_id,content,chunk_index,index_version) VALUES (:id,'Texte conservé',0,1)"
                ),
                {"id": document_id},
            )

            path = (
                Path(__file__).resolve().parents[1]
                / "alembic"
                / "versions"
                / "2026_11_25_0014_complete_tenant_schemas.py"
            )
            spec = importlib.util.spec_from_file_location("migration_0014", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()

            tables = sa.text("SELECT tablename FROM pg_tables WHERE schemaname=:schema")
            assert set(connection.execute(tables, {"schema": schema}).scalars()) == set(
                connection.execute(tables, {"schema": "tenant_template"}).scalars()
            )
            assert (
                connection.execute(
                    sa.text(f'SELECT content FROM "{schema}".kb_chunks WHERE document_id=:id'),
                    {"id": document_id},
                ).scalar_one()
                == "Texte conservé"
            )
            assert (
                connection.execute(
                    sa.text(
                        f'SELECT active_index_version FROM "{schema}".kb_documents WHERE id=:id'
                    ),
                    {"id": document_id},
                ).scalar_one()
                == 1
            )
            connection.rollback()
    finally:
        engine.dispose()
