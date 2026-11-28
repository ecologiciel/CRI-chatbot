"""Prepare an encrypted agent reply outbox, without enabling sends.

Revision ID: 0019c_reply
Revises: 0019b_wa
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019c_reply"
down_revision: str = "0019b_wa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_reply_outbox_events",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("escalation_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("phone_number_id", sa.String(32), nullable=False),
        sa.Column("recipient_fingerprint", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("outcome_code", sa.String(64), nullable=True),
        sa.Column("review_decision", sa.String(32), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("state IN ('pending', 'processing', 'accepted', 'uncertain', 'follow_up', 'resolved', 'canceled')", name="ck_agent_reply_state"),
        sa.CheckConstraint("attempts IN (0, 1) AND key_version > 0", name="ck_agent_reply_counters"),
        sa.CheckConstraint("state <> 'pending' OR attempts = 0", name="ck_agent_reply_no_requeue"),
        sa.CheckConstraint("state <> 'accepted' OR (provider_message_id IS NOT NULL AND length(provider_message_id) > 0)", name="ck_agent_reply_accepted_id"),
        sa.CheckConstraint("(state = 'resolved' AND review_decision IS NOT NULL AND review_decision IN ('confirmed_delivered', 'confirmed_not_sent', 'unknown_no_retry') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) OR (state <> 'resolved' AND review_decision IS NULL AND reviewed_by IS NULL AND reviewed_at IS NULL)", name="ck_agent_reply_review"),
        sa.CheckConstraint("(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)", name="ck_agent_reply_lease"),
        sa.CheckConstraint("recipient_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_agent_reply_recipient"),
        schema="public",
    )
    op.create_index("uq_agent_reply_request", "agent_reply_outbox_events", ["tenant_id", "request_key"], unique=True, schema="public")
    op.create_index("uq_agent_reply_sequence", "agent_reply_outbox_events", ["sequence"], unique=True, schema="public")
    op.create_index("ix_agent_reply_queue", "agent_reply_outbox_events", ["state", "created_at"], schema="public")
    op.create_index("ix_agent_reply_conversation", "agent_reply_outbox_events", ["tenant_id", "conversation_id", "sequence"], schema="public")


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before removing the agent reply outbox")
