"""create internal whitelist table

Revision ID: 006
Revises: 005
Create Date: 2026-03-27

Creates:
- internal_whitelist table in tenant_template schema
- Indexes: phone (unique), (phone, is_active) composite, added_by, is_active
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    op.create_table(
        "internal_whitelist",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "phone",
            sa.String(20),
            nullable=False,
            comment="E.164 format, e.g. +212612345678",
        ),
        sa.Column(
            "label",
            sa.String(255),
            nullable=True,
            comment="Optional display label (e.g. employee name or department)",
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
            comment="Admin note about why this number was whitelisted",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["added_by"],
            ["public.admins.id"],
            ondelete="SET NULL",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_internal_whitelist_phone",
        "internal_whitelist",
        ["phone"],
        unique=True,
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_internal_whitelist_phone_active",
        "internal_whitelist",
        ["phone", "is_active"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_internal_whitelist_added_by",
        "internal_whitelist",
        ["added_by"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_internal_whitelist_is_active",
        "internal_whitelist",
        ["is_active"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("internal_whitelist", schema=TENANT_SCHEMA)
