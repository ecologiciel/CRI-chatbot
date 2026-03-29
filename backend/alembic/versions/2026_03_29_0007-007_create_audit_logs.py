"""create audit_logs table (public schema, INSERT ONLY)

Revision ID: 007
Revises: 006
Create Date: 2026-03-29

Creates:
- audit_logs table in PUBLIC schema (shared across all tenants)
- 5 indexes for efficient querying by tenant, date, user, action, resource
- INSERT ONLY policy documented via COMMENT ON TABLE

Security: This table is designed as an immutable append-only ledger.
The application role should only have INSERT + SELECT privileges.
See scripts/apply_audit_policy.sql for production GRANT/REVOKE commands.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- audit_logs table (public schema) ---
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_slug", sa.String(50), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_type", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )

    # --- Indexes ---
    op.create_index(
        "ix_audit_tenant",
        "audit_logs",
        ["tenant_slug"],
        schema="public",
    )
    # DESC index for chronological queries — use raw SQL
    op.execute(
        "CREATE INDEX ix_audit_created ON public.audit_logs (created_at DESC)"
    )
    # Partial index — only rows with a known user
    op.execute(
        "CREATE INDEX ix_audit_user ON public.audit_logs (user_id) "
        "WHERE user_id IS NOT NULL"
    )
    op.create_index(
        "ix_audit_action",
        "audit_logs",
        ["action"],
        schema="public",
    )
    op.create_index(
        "ix_audit_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
        schema="public",
    )

    # --- Document the INSERT ONLY policy ---
    op.execute(
        "COMMENT ON TABLE public.audit_logs IS "
        "'Journal d''audit immuable. INSERT ONLY — UPDATE/DELETE interdits "
        "pour le rôle applicatif. Rétention : 12 mois PostgreSQL, "
        "24 mois MinIO (SECURITE.4).'"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_resource", table_name="audit_logs", schema="public")
    op.drop_index("ix_audit_action", table_name="audit_logs", schema="public")
    op.execute("DROP INDEX IF EXISTS public.ix_audit_user")
    op.execute("DROP INDEX IF EXISTS public.ix_audit_created")
    op.drop_index("ix_audit_tenant", table_name="audit_logs", schema="public")
    op.drop_table("audit_logs", schema="public")
