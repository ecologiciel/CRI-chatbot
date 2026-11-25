"""add tenant demo configuration and web contact source

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TYPE public.contactsource ADD VALUE IF NOT EXISTS 'web'"))
    with op.batch_alter_table("tenants", schema="public") as batch:
        batch.add_column(
            sa.Column(
                "public_config",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            )
        )
        batch.add_column(
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch.add_column(
            sa.Column(
                "conversation_retention_days",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("90"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenants", schema="public") as batch:
        batch.drop_column("conversation_retention_days")
        batch.drop_column("is_demo")
        batch.drop_column("public_config")
    # PostgreSQL enum values are intentionally not removed: production-safe downgrade.
