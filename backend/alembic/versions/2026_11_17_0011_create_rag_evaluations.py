"""create tenant RAG evaluation monitoring tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    op.create_table(
        "rag_evaluation_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False, server_default="fr"),
        sa.Column(
            "expected_document_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expects_abstention", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("human_faithfulness", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_rag_evaluation_cases_active",
        "rag_evaluation_cases",
        ["is_active"],
        schema=TENANT_SCHEMA,
    )
    op.create_table(
        "rag_evaluation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_rag_evaluation_runs_created_at",
        "rag_evaluation_runs",
        ["created_at"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("rag_evaluation_runs", schema=TENANT_SCHEMA)
    op.drop_table("rag_evaluation_cases", schema=TENANT_SCHEMA)
