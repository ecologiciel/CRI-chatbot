"""Add per-document index generations to the template and existing tenants.

Revision ID: 0013
Revises: 0012
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schemas() -> list[str]:
    bind = op.get_bind()
    slugs = bind.execute(sa.text("SELECT slug FROM public.tenants ORDER BY slug")).scalars().all()
    schemas = ["tenant_template"]
    for slug in slugs:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", slug):
            raise ValueError("Invalid tenant slug in database")
        schema = f"tenant_{slug}"
        if schema == "tenant_template" or len(schema) > 63:
            raise ValueError("Tenant schema collision or invalid length")
        exists = bind.execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = :name)"),
            {"name": schema},
        ).scalar_one()
        if not exists:
            raise RuntimeError(f"Missing tenant schema: {schema}")
        schemas.append(schema)
    return schemas


def upgrade() -> None:
    for schema in _schemas():
        op.add_column(
            "kb_documents",
            sa.Column("active_index_version", sa.Integer(), nullable=True),
            schema=schema,
        )
        op.add_column(
            "kb_chunks",
            sa.Column("index_version", sa.Integer(), nullable=False, server_default="1"),
            schema=schema,
        )
        # LIKE INCLUDING ALL can give cloned constraints different names.
        matches = (
            op.get_bind()
            .execute(
                sa.text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = :schema AND t.relname = 'kb_chunks' AND c.contype = 'u'
              AND (SELECT array_agg(a.attname ORDER BY k.ordinality)
                   FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality)
                   JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum)
                  = ARRAY['document_id', 'chunk_index']::name[]
        """),
                {"schema": schema},
            )
            .scalars()
            .all()
        )
        if len(matches) != 1:
            raise RuntimeError(f"Expected one legacy chunk uniqueness constraint in {schema}")
        op.drop_constraint(matches[0], "kb_chunks", schema=schema, type_="unique")
        op.create_unique_constraint(
            "uq_kb_chunks_doc_version_index",
            "kb_chunks",
            ["document_id", "index_version", "chunk_index"],
            schema=schema,
        )
        # Set the legacy active generation based on actual chunk rows, even if
        # a prior interrupted operation left the document status as pending.
        quoted = op.get_bind().dialect.identifier_preparer.quote_schema(schema)
        op.execute(
            sa.text(
                f"UPDATE {quoted}.kb_documents d SET active_index_version = 1 WHERE EXISTS (SELECT 1 FROM {quoted}.kb_chunks c WHERE c.document_id = d.id)"
            )
        )


def downgrade() -> None:
    raise RuntimeError("Index generation migration requires restore from a verified backup")
