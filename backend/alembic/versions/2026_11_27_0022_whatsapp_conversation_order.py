"""Prepare opaque conversation identities for ordered WhatsApp processing.

Revision ID: 0022
Revises: 0021

Existing rows remain NULL and require explicit reconciliation before any
ordered worker can process them. Pending legacy events are quarantined as
uncertain so an operator can find and review them; they are never resent.
This migration does not enable the worker.
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
        "whatsapp_inbox_events", sa.Column("arrival_sequence", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        schema="public",
    )
    op.add_column(
        "whatsapp_inbox_events", sa.Column("is_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="public",
    )
    # Legacy messages cannot be assigned a conversation safely from metadata
    # alone. Expose pending ones to the existing manual review workflow rather
    # than leaving an unclaimable, invisible tenant-wide queue blocker.
    # In-flight events keep their lease and are quarantined by the reaper.
    op.execute(
        "UPDATE public.whatsapp_inbox_events "
        "SET state = 'uncertain', updated_at = clock_timestamp() "
        "WHERE sender_fingerprint IS NULL AND state = 'pending'"
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
    # Removing sequence and grouping data from a populated inbox is not a
    # reversible rollback. Lock out concurrent writers and refuse it.
    op.execute("LOCK TABLE public.whatsapp_inbox_events IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM public.whatsapp_inbox_events)")).scalar_one():
        raise RuntimeError("Cannot downgrade ordered WhatsApp inbox while events exist")
    op.drop_index("ix_wa_inbox_conversation_order", table_name="whatsapp_inbox_events", schema="public")
    op.drop_index("uq_wa_inbox_arrival_sequence", table_name="whatsapp_inbox_events", schema="public")
    op.drop_constraint("ck_wa_inbox_sender_fingerprint", "whatsapp_inbox_events", schema="public", type_="check")
    op.drop_column("whatsapp_inbox_events", "is_opt_out", schema="public")
    op.drop_column("whatsapp_inbox_events", "arrival_sequence", schema="public")
    op.drop_column("whatsapp_inbox_events", "sender_fingerprint", schema="public")
