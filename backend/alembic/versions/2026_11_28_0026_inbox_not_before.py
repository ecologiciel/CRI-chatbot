"""Delay side-effect-free WhatsApp inbox attempts without losing order.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_inbox_events",
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before reverting deferred inbox events")
