"""Create encrypted durable WhatsApp inbox storage, initially unused.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_inbox_events",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("phone_number_id", sa.String(32), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'uncertain', 'follow_up', 'resolved', 'completed')",
            name="ck_wa_inbox_state",
        ),
        sa.CheckConstraint("key_version > 0 AND attempts >= 0", name="ck_wa_inbox_counters"),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_until IS NOT NULL AND lease_token IS NOT NULL) "
            "OR (state <> 'processing' AND lease_until IS NULL AND lease_token IS NULL)",
            name="ck_wa_inbox_lease",
        ),
        schema="public",
    )
    op.create_index(
        "uq_wa_inbox_tenant_message",
        "whatsapp_inbox_events",
        ["tenant_id", "provider_message_id"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ix_wa_inbox_pending", "whatsapp_inbox_events", ["state", "created_at"], schema="public"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before removing durable WhatsApp events")
