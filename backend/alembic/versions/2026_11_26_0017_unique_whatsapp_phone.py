"""Prevent ambiguous WhatsApp phone routing across institutions.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL rejects the index if existing duplicates exist. This is
    # intentional: do not arbitrarily reassign or delete a tenant's channel.
    op.execute(
        "CREATE UNIQUE INDEX uq_tenants_whatsapp_phone ON public.tenants "
        "((whatsapp_config ->> 'phone_number_id')) "
        "WHERE whatsapp_config ->> 'phone_number_id' IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.uq_tenants_whatsapp_phone")
