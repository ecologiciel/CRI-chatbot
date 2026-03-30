"""create incitation tables

Revision ID: 003
Revises: 002
Create Date: 2026-03-26

Creates:
- incentive_categories table in tenant_template (tree structure)
- incentive_items table in tenant_template (leaf content)
- All required indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    # ── 1. Create incentive_categories table ──
    op.create_table(
        "incentive_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Null = root category",
        ),
        sa.Column("name_fr", sa.String(255), nullable=False, comment="French name"),
        sa.Column("name_ar", sa.String(255), nullable=True, comment="Arabic name"),
        sa.Column("name_en", sa.String(255), nullable=True, comment="English name"),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column(
            "order_index",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Sort order within sibling categories",
        ),
        sa.Column(
            "is_leaf",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="True = contains items, no sub-categories",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "icon",
            sa.String(50),
            nullable=True,
            comment="Lucide icon name for back-office",
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
            ["parent_id"],
            [f"{TENANT_SCHEMA}.incentive_categories.id"],
            ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_categories_parent_id",
        "incentive_categories",
        ["parent_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_categories_order_index",
        "incentive_categories",
        ["order_index"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_categories_is_active",
        "incentive_categories",
        ["is_active"],
        schema=TENANT_SCHEMA,
    )

    # ── 2. Create incentive_items table ──
    op.create_table(
        "incentive_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("title_fr", sa.String(500), nullable=False, comment="French title"),
        sa.Column("title_ar", sa.String(500), nullable=True, comment="Arabic title"),
        sa.Column("title_en", sa.String(500), nullable=True, comment="English title"),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column(
            "conditions",
            sa.Text(),
            nullable=True,
            comment="Eligibility conditions (free text)",
        ),
        sa.Column(
            "legal_reference",
            sa.String(500),
            nullable=True,
            comment="Law/decree reference",
        ),
        sa.Column(
            "eligibility_criteria",
            postgresql.JSONB(),
            nullable=True,
            comment="Structured eligibility criteria",
        ),
        sa.Column(
            "documents_required",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="List of required documents",
        ),
        sa.Column(
            "order_index",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
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
            ["category_id"],
            [f"{TENANT_SCHEMA}.incentive_categories.id"],
            ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_items_category_id",
        "incentive_items",
        ["category_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_items_order_index",
        "incentive_items",
        ["order_index"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_incentive_items_is_active",
        "incentive_items",
        ["is_active"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    # Drop in reverse FK-dependency order
    op.drop_table("incentive_items", schema=TENANT_SCHEMA)
    op.drop_table("incentive_categories", schema=TENANT_SCHEMA)
