"""Prepare a durable import request registry, initially unused.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dossier_import_requests",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(160), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("mapping_sha256", sa.String(64), nullable=False),
        sa.Column("sync_config_id", sa.UUID(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("sync_log_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_code", sa.String(64), nullable=True),
        sa.Column("review_state", sa.String(16), nullable=False, server_default="open"),
        sa.Column("review_outcome", sa.String(16), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'completed', 'failed', 'uncertain')",
            name="ck_dossier_import_request_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_dossier_import_request_attempts"),
        sa.CheckConstraint(
            "(review_state IN ('open', 'follow_up') AND review_outcome IS NULL) OR "
            "(review_state = 'closed' AND review_outcome IS NOT NULL AND review_outcome IN ('applied', 'not_applied'))",
            name="ck_dossier_import_request_review",
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_dossier_import_request_lease",
        ),
        schema="public",
    )
    op.create_index(
        "uq_dossier_import_request_object",
        "dossier_import_requests",
        ["tenant_id", "object_key"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ix_dossier_import_request_queue",
        "dossier_import_requests",
        ["tenant_id", "state", "created_at"],
        schema="public",
    )
    op.create_index(
        "uq_dossier_import_active_content",
        "dossier_import_requests",
        ["tenant_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text("state <> 'failed'"),
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup before removing durable import requests")
