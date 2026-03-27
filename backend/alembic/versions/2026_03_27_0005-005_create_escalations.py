"""create escalations table

Revision ID: 005
Revises: 004
Create Date: 2026-03-27

Creates:
- escalationtrigger, escalationpriority, escalationstatus ENUM types in public schema
- escalations table in tenant_template schema
- Composite index (status, priority) for queue sorting
- Indexes on assigned_to, created_at, conversation_id
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: str = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── ENUM types (public schema, shared across tenants) ──

escalationtrigger = postgresql.ENUM(
    "explicit_request", "rag_failure", "sensitive_topic",
    "negative_feedback", "otp_timeout", "manual",
    name="escalationtrigger", schema="public", create_type=False,
)
escalationpriority = postgresql.ENUM(
    "high", "medium", "low",
    name="escalationpriority", schema="public", create_type=False,
)
escalationstatus = postgresql.ENUM(
    "pending", "assigned", "in_progress", "resolved", "closed",
    name="escalationstatus", schema="public", create_type=False,
)

ALL_ENUMS = [escalationtrigger, escalationpriority, escalationstatus]

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Create ENUM types in public schema ──
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ── 2. Create escalations table ──
    op.create_table(
        "escalations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        # Foreign keys
        sa.Column(
            "conversation_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "assigned_to", postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Trigger & priority
        sa.Column(
            "trigger_type", escalationtrigger,
            nullable=False,
        ),
        sa.Column(
            "priority", escalationpriority,
            nullable=False,
        ),
        # Context
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        # Status
        sa.Column(
            "status", escalationstatus,
            nullable=False, server_default="pending",
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        # Timestamps
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{TENANT_SCHEMA}.conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["public.admins.id"],
            ondelete="SET NULL",
        ),
        schema=TENANT_SCHEMA,
    )

    # ── 3. Create indexes ──
    op.create_index(
        "ix_escalations_status_priority",
        "escalations",
        ["status", "priority"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_escalations_assigned_to",
        "escalations",
        ["assigned_to"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_escalations_created_at",
        "escalations",
        ["created_at"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_escalations_conversation_id",
        "escalations",
        ["conversation_id"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    # ── 1. Drop table ──
    op.drop_table("escalations", schema=TENANT_SCHEMA)

    # ── 2. Drop ENUM types ──
    bind = op.get_bind()
    for enum in reversed(ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
