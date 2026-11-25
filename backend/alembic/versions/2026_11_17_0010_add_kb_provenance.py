"""add KB provenance and validation lifecycle

Revision ID: 0010
Revises: 009
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    bind = op.get_bind()
    for value in ("pending_validation", "rejected", "expired"):
        bind.execute(
            sa.text(f"ALTER TYPE public.kbdocumentstatus ADD VALUE IF NOT EXISTS '{value}'")
        )

    with op.batch_alter_table("kb_documents", schema=TENANT_SCHEMA) as batch:
        batch.add_column(sa.Column("source_authority", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("source_reference", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("source_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("published_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column("validated_by", sa.UUID(), nullable=True))
        batch.add_column(sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_documents", schema=TENANT_SCHEMA) as batch:
        for column in (
            "validated_at",
            "validated_by",
            "expires_at",
            "verified_at",
            "published_at",
            "source_version",
            "source_reference",
            "source_authority",
        ):
            batch.drop_column(column)
