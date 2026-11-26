"""Add tenant-scoped document importer and validator roles.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL cannot remove enum values in a simple reversible migration.
    # This migration contains no writes that use the new values.
    op.execute("ALTER TYPE public.adminrole ADD VALUE IF NOT EXISTS 'document_importer'")
    op.execute("ALTER TYPE public.adminrole ADD VALUE IF NOT EXISTS 'document_validator'")


def downgrade() -> None:
    raise RuntimeError("Removing PostgreSQL enum values requires a verified backup")
