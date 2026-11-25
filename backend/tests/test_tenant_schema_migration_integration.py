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
            index_path = path.with_name("2026_11_25_0015_kb_fulltext_index.py")
            index_spec = importlib.util.spec_from_file_location("migration_0015", index_path)
            index_module = importlib.util.module_from_spec(index_spec)
            index_spec.loader.exec_module(index_module)
            index_module.op = Operations(MigrationContext.configure(connection))
            index_module.upgrade()
            indexes = (
                connection.execute(
                    sa.text(
                        "SELECT schemaname FROM pg_indexes WHERE indexname='ix_kb_chunks_content_fts' "
                        "AND schemaname IN (:tenant, 'tenant_template')"
                    ),
                    {"tenant": schema},
                )
                .scalars()
                .all()
            )
            assert set(indexes) == {schema, "tenant_template"}
            connection.execute(sa.text("SET LOCAL enable_seqscan=off"))
            quoted = connection.dialect.identifier_preparer.quote(schema)
            plan = (
                connection.execute(
                    sa.text(
                        f"EXPLAIN SELECT id FROM {quoted}.kb_chunks "
                        "WHERE to_tsvector('simple'::regconfig, content) "
                        "@@ websearch_to_tsquery('simple'::regconfig, 'Texte')"
                    )
                )
                .scalars()
                .all()
            )
            assert any("ix_kb_chunks_content_fts" in line for line in plan)
            connection.rollback()
    finally:
        engine.dispose()
