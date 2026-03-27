"""create campaigns and campaign_recipients tables

Revision ID: 004
Revises: 003
Create Date: 2026-03-27

Creates:
- campaignstatus and recipientstatus ENUM types in public schema
- campaigns table in tenant_template schema
- campaign_recipients table in tenant_template schema
- All required indexes including composite and partial
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: str = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── ENUM types (public schema, shared across tenants) ──

campaignstatus = postgresql.ENUM(
    "draft", "scheduled", "sending", "paused", "completed", "failed",
    name="campaignstatus", schema="public", create_type=False,
)

recipientstatus = postgresql.ENUM(
    "pending", "sent", "delivered", "read", "failed",
    name="recipientstatus", schema="public", create_type=False,
)

ALL_ENUMS = [campaignstatus, recipientstatus]

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Create ENUM types ──
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ── 2. Create campaigns table ──
    op.create_table(
        "campaigns",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        # Campaign info
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # WhatsApp template
        sa.Column("template_id", sa.String(255), nullable=False),
        sa.Column("template_name", sa.String(255), nullable=False),
        sa.Column("template_language", sa.String(10), server_default="fr", nullable=False),
        # Audience
        sa.Column(
            "audience_filter", postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("audience_count", sa.Integer(), server_default="0", nullable=False),
        # Variable mapping
        sa.Column(
            "variable_mapping", postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        # Status
        sa.Column(
            "status", campaignstatus,
            server_default="draft", nullable=False,
        ),
        # Scheduling
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Aggregated stats
        sa.Column(
            "stats", postgresql.JSONB(),
            server_default=sa.text(
                """'{"sent": 0, "delivered": 0, "read": 0, "failed": 0, "total": 0}'::jsonb"""
            ),
            nullable=False,
        ),
        # Traceability
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        # Timestamps
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["public.admins.id"],
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_campaigns_status", "campaigns", ["status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_campaigns_scheduled_at", "campaigns", ["scheduled_at"],
        schema=TENANT_SCHEMA,
        postgresql_where=sa.text("scheduled_at IS NOT NULL"),
    )
    op.create_index(
        "ix_campaigns_created_by", "campaigns", ["created_by"],
        schema=TENANT_SCHEMA,
    )

    # ── 3. Create campaign_recipients table ──
    op.create_table(
        "campaign_recipients",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        # Foreign keys
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Delivery status
        sa.Column(
            "status", recipientstatus,
            server_default="pending", nullable=False,
        ),
        # Delivery details
        sa.Column("whatsapp_message_id", sa.String(100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamp
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{TENANT_SCHEMA}.campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], [f"{TENANT_SCHEMA}.contacts.id"],
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_recipients_campaign_status", "campaign_recipients",
        ["campaign_id", "status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_recipients_contact_id", "campaign_recipients", ["contact_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_recipients_whatsapp_msg_id", "campaign_recipients",
        ["whatsapp_message_id"],
        schema=TENANT_SCHEMA,
        postgresql_where=sa.text("whatsapp_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop campaign_recipients FIRST (FK dependency on campaigns)
    op.drop_table("campaign_recipients", schema=TENANT_SCHEMA)
    op.drop_table("campaigns", schema=TENANT_SCHEMA)

    # Drop ENUM types
    bind = op.get_bind()
    for enum in reversed(ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
