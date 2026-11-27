"""Prepare a durable dossier notification outbox, initially unused.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox_events",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("history_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'sent', 'skipped', 'uncertain')",
            name="ck_notification_outbox_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_notification_outbox_lease",
        ),
        schema="public",
    )
    op.create_index(
        "uq_notification_outbox_history",
        "notification_outbox_events",
        ["tenant_id", "history_id"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ix_notification_outbox_queue",
        "notification_outbox_events",
        ["tenant_id", "state", "created_at"],
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before removing notification outbox events")
