"""Integration test requiring an explicitly supplied disposable PostgreSQL database."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_existing_tenant_chunks():
    dsn = os.environ.get("RAG_MIGRATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set RAG_MIGRATION_TEST_DSN to a fresh disposable database")
    engine = sa.create_engine(dsn)
    try:
        with engine.begin() as connection:
            assert (
                connection.execute(sa.text("SELECT current_database()")).scalar_one()
                == "rag_migration_test"
            )
            assert connection.execute(
                sa.text("SELECT to_regclass('public.tenants') IS NULL")
            ).scalar_one(), "Database must be empty"
            connection.execute(sa.text("CREATE TABLE public.tenants (slug text NOT NULL)"))
            connection.execute(sa.text("INSERT INTO public.tenants VALUES ('onssa')"))
            connection.execute(sa.text("CREATE SCHEMA tenant_template"))
            connection.execute(sa.text("CREATE SCHEMA tenant_onssa"))
            connection.execute(
                sa.text("CREATE TABLE tenant_template.kb_documents (id uuid PRIMARY KEY)")
            )
            connection.execute(
                sa.text(
                    "CREATE TABLE tenant_template.kb_chunks (document_id uuid NOT NULL, chunk_index integer NOT NULL, CONSTRAINT uq_kb_chunks_doc_index UNIQUE(document_id, chunk_index))"
                )
            )
            connection.execute(
                sa.text(
                    "CREATE TABLE tenant_onssa.kb_documents (LIKE tenant_template.kb_documents INCLUDING ALL)"
                )
            )
            connection.execute(
                sa.text(
                    "CREATE TABLE tenant_onssa.kb_chunks (LIKE tenant_template.kb_chunks INCLUDING ALL)"
                )
            )
            document_id = uuid.uuid4()
            connection.execute(
                sa.text("INSERT INTO tenant_onssa.kb_documents VALUES (:id)"), {"id": document_id}
            )
            connection.execute(
                sa.text("INSERT INTO tenant_onssa.kb_chunks VALUES (:id, 0)"), {"id": document_id}
            )

            path = (
                Path(__file__).resolve().parents[1]
                / "alembic"
                / "versions"
                / "2026_11_25_0013_kb_index_versions.py"
            )
            spec = importlib.util.spec_from_file_location("migration_0013", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()

            assert (
                connection.execute(
                    sa.text(
                        "SELECT active_index_version FROM tenant_onssa.kb_documents WHERE id=:id"
                    ),
                    {"id": document_id},
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT index_version FROM tenant_onssa.kb_chunks WHERE document_id=:id"
                    ),
                    {"id": document_id},
                ).scalar_one()
                == 1
            )
            connection.execute(
                sa.text(
                    "INSERT INTO tenant_onssa.kb_chunks (document_id, chunk_index, index_version) VALUES (:id, 0, 2)"
                ),
                {"id": document_id},
            )
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM tenant_onssa.kb_chunks WHERE document_id=:id"),
                    {"id": document_id},
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()
