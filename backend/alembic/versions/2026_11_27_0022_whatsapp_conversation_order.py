"""Prepare opaque conversation identities for ordered WhatsApp processing.

Revision ID: 0022
Revises: 0021

Existing rows remain NULL and require explicit reconciliation before any
ordered worker can process them. This migration does not enable the worker.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("whatsapp_inbox_events", sa.Column("sender_fingerprint", sa.String(64)), schema="public")
    op.add_column(
        "whatsapp_inbox_events", sa.Column("arrival_sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        schema="public",
    )
    op.add_column(
        "whatsapp_inbox_events", sa.Column("is_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="public",
    )
    op.create_check_constraint(
        "ck_wa_inbox_sender_fingerprint", "whatsapp_inbox_events",
        "sender_fingerprint IS NULL OR sender_fingerprint ~ '^[0-9a-f]{64}$'", schema="public",
    )
    op.create_index(
        "ix_wa_inbox_conversation_order", "whatsapp_inbox_events",
        ["tenant_id", "sender_fingerprint", "arrival_sequence"], schema="public",
        postgresql_where=sa.text("state IN ('pending', 'processing', 'uncertain', 'follow_up')"),
    )


def downgrade() -> None:
    op.drop_index("ix_wa_inbox_conversation_order", table_name="whatsapp_inbox_events", schema="public")
    op.drop_constraint("ck_wa_inbox_sender_fingerprint", "whatsapp_inbox_events", schema="public", type_="check")
    op.drop_column("whatsapp_inbox_events", "is_opt_out", schema="public")
    op.drop_column("whatsapp_inbox_events", "arrival_sequence", schema="public")
    op.drop_column("whatsapp_inbox_events", "sender_fingerprint", schema="public")
