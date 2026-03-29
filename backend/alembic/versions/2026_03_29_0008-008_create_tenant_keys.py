"""create tenant_keys table (public schema, envelope encryption)

Revision ID: 008
Revises: 007
Create Date: 2026-03-29

Creates:
- tenant_keys table in PUBLIC schema (shared across all tenants)
- Partial unique index: one active key per tenant
- FK to public.tenants with CASCADE delete

Each row stores a per-tenant AES-256-GCM data key, itself encrypted
by the platform master key (KMS_MASTER_KEY env var).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tenant_keys table (public schema) ---
    op.create_table(
        "tenant_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "algorithm",
            sa.String(50),
            server_default="AES-256-GCM",
            nullable=False,
        ),
        sa.Column(
            "key_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "rotated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            name="fk_tenant_keys_tenant",
            ondelete="CASCADE",
        ),
        schema="public",
    )

    # --- Indexes ---
    # Partial unique index: exactly one active key per tenant
    op.execute(
        "CREATE UNIQUE INDEX ix_tenant_keys_active "
        "ON public.tenant_keys (tenant_id) "
        "WHERE is_active = TRUE"
    )
    op.create_index(
        "ix_tenant_keys_tenant",
        "tenant_keys",
        ["tenant_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_keys_tenant", table_name="tenant_keys", schema="public")
    op.execute("DROP INDEX IF EXISTS public.ix_tenant_keys_active")
    op.drop_table("tenant_keys", schema="public")
