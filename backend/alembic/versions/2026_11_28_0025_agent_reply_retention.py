"""Allow terminal agent reply payloads to be redacted without losing replay fences.

Revision ID: 0025
Revises: 0024
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "agent_reply_outbox_events"
    op.drop_constraint("ck_agent_reply_recipient", table, type_="check", schema="public")
    op.drop_constraint("ck_agent_reply_accepted_id", table, type_="check", schema="public")
    for name in ("contact_id", "phone_number_id", "recipient_fingerprint"):
        op.alter_column(table, name, nullable=True, schema="public")
    op.create_check_constraint(
        "ck_agent_reply_recipient", table,
        "(redacted_at IS NULL AND contact_id IS NOT NULL AND phone_number_id IS NOT NULL "
        "AND recipient_fingerprint IS NOT NULL AND recipient_fingerprint ~ '^[0-9a-f]{64}$') OR "
        "(redacted_at IS NOT NULL AND contact_id IS NULL AND phone_number_id IS NULL "
        "AND recipient_fingerprint IS NULL)", schema="public",
    )
    op.create_check_constraint(
        "ck_agent_reply_accepted_id", table,
        "state <> 'accepted' OR redacted_at IS NOT NULL OR "
        "(provider_message_id IS NOT NULL AND length(provider_message_id) > 0)", schema="public",
    )
    op.create_check_constraint(
        "ck_agent_reply_redaction", table,
        "redacted_at IS NULL OR (state IN ('accepted', 'resolved', 'canceled') "
        "AND ciphertext = '' AND provider_message_id IS NULL)", schema="public",
    )
    op.create_index(
        "ix_agent_reply_retention", table, ["tenant_id", "updated_at", "id"], schema="public",
        postgresql_where=sa.text("redacted_at IS NULL AND state IN ('accepted', 'resolved', 'canceled')"),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before reverting agent reply retention")
