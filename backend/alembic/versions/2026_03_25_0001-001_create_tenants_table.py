"""create tenants table

Revision ID: 001
Revises: None
Create Date: 2026-03-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ENUM type for tenant status — created in public schema
tenantstatus = postgresql.ENUM(
    "active",
    "inactive",
    "provisioning",
    name="tenantstatus",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    # Create the ENUM type first
    tenantstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False, comment="Nom complet du CRI"),
        sa.Column(
            "slug",
            sa.String(50),
            nullable=False,
            unique=True,
            comment="Identifiant unique de routage multi-tenant",
        ),
        sa.Column("region", sa.String(255), nullable=False, comment="Region couverte"),
        sa.Column("logo_url", sa.Text(), nullable=True, comment="URL logo SVG/PNG max 200x60"),
        sa.Column(
            "accent_color", sa.String(20), nullable=True, comment="CSS HSL color pour tenant accent"
        ),
        sa.Column(
            "whatsapp_config",
            postgresql.JSONB(),
            nullable=True,
            comment="phone_number_id, access_token, verify_token, templates",
        ),
        sa.Column(
            "status",
            tenantstatus,
            server_default="provisioning",
            nullable=False,
        ),
        sa.Column("max_contacts", sa.Integer(), server_default="20000", nullable=False),
        sa.Column("max_messages_per_year", sa.Integer(), server_default="100000", nullable=False),
        sa.Column("max_admins", sa.Integer(), server_default="10", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True, schema="public")
    op.create_index("ix_tenants_status", "tenants", ["status"], schema="public")


def downgrade() -> None:
    op.drop_index("ix_tenants_status", table_name="tenants", schema="public")
    op.drop_index("ix_tenants_slug", table_name="tenants", schema="public")
    op.drop_table("tenants", schema="public")
    tenantstatus.drop(op.get_bind(), checkfirst=True)
