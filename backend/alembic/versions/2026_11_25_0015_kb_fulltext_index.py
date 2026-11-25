"""Index tenant knowledge chunks for lexical retrieval.

Revision ID: 0015
Revises: 0014
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    quote = bind.dialect.identifier_preparer.quote
    slugs = bind.execute(sa.text("SELECT slug FROM public.tenants ORDER BY slug")).scalars()
    schemas = ["tenant_template"]
    for slug in slugs:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", slug):
            raise ValueError("Invalid tenant slug in database")
        schema = f"tenant_{slug}"
        if schema == "tenant_template" or len(schema) > 63:
            raise ValueError("Tenant schema collision or invalid length")
        schemas.append(schema)
    for schema in schemas:
        exists = bind.execute(
            sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{schema}.kb_chunks"}
        ).scalar_one()
        if not exists:
            raise RuntimeError(f"Missing knowledge chunks table in {schema}")
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_kb_chunks_content_fts ON {quote(schema)}.kb_chunks "
                "USING gin (to_tsvector('simple'::regconfig, content))"
            )
        )


def downgrade() -> None:
    raise RuntimeError("Restoring the previous schema requires a verified backup")
