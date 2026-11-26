"""Create encrypted WhatsApp delivery status inbox, initially unused.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_status_events",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("phone_number_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "state IN ('pending', 'applied', 'uncertain')", name="ck_wa_status_state"
        ),
        sa.CheckConstraint("key_version > 0", name="ck_wa_status_key_version"),
        schema="public",
    )
    op.create_index(
        "uq_wa_status_fingerprint",
        "whatsapp_status_events",
        ["tenant_id", "fingerprint"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ix_wa_status_pending", "whatsapp_status_events", ["state", "created_at"], schema="public"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before removing WhatsApp status events")
