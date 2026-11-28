"""Prepare ordered, deferred WhatsApp inbox processing without enabling it.

Revision ID: 0019b_wa
Revises: 0019a_phone
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019b_wa"
down_revision: str = "0019a_phone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("whatsapp_inbox_events", sa.Column("sender_fingerprint", sa.String(64)), schema="public")
    op.add_column(
        "whatsapp_inbox_events",
        sa.Column("arrival_sequence", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        schema="public",
    )
    op.add_column(
        "whatsapp_inbox_events", sa.Column("is_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="public",
    )
    op.add_column("whatsapp_inbox_events", sa.Column("not_before", sa.DateTime(timezone=True)), schema="public")
    op.execute(
        "UPDATE public.whatsapp_inbox_events SET state='uncertain', updated_at=clock_timestamp() "
        "WHERE sender_fingerprint IS NULL AND state='pending'"
    )
    op.create_check_constraint(
        "ck_wa_inbox_sender_fingerprint", "whatsapp_inbox_events",
        "sender_fingerprint IS NULL OR sender_fingerprint ~ '^[0-9a-f]{64}$'", schema="public",
    )
    op.create_index(
        "uq_wa_inbox_arrival_sequence", "whatsapp_inbox_events", ["arrival_sequence"],
        schema="public", unique=True,
    )
    op.create_index(
        "ix_wa_inbox_conversation_order", "whatsapp_inbox_events",
        ["tenant_id", "sender_fingerprint", "arrival_sequence"], schema="public",
        postgresql_where=sa.text("state IN ('pending', 'processing', 'uncertain', 'follow_up')"),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before reverting ordered WhatsApp inbox events")
