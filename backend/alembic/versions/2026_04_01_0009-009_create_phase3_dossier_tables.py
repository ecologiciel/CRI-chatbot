"""create phase 3 dossier tables

Revision ID: 009
Revises: 008
Create Date: 2026-04-01

Creates:
- dossierstatut, syncstatus, syncsourcetype, syncprovidertype ENUM types
  in public schema
- sync_logs table in tenant_template schema
- sync_configs table in tenant_template schema
- dossiers table in tenant_template schema
- dossier_history table in tenant_template schema
- All required indexes including composite (dossier_id, changed_at)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009"
down_revision: str = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── ENUM types (public schema, shared across tenants) ──

dossierstatut = postgresql.ENUM(
    "en_cours",
    "valide",
    "rejete",
    "en_attente",
    "complement",
    "incomplet",
    name="dossierstatut",
    schema="public",
    create_type=False,
)
syncstatus = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    name="syncstatus",
    schema="public",
    create_type=False,
)
syncsourcetype = postgresql.ENUM(
    "excel",
    "csv",
    "api_rest",
    "manual",
    name="syncsourcetype",
    schema="public",
    create_type=False,
)
syncprovidertype = postgresql.ENUM(
    "excel_csv",
    "api_rest",
    "db_link",
    name="syncprovidertype",
    schema="public",
    create_type=False,
)

ALL_ENUMS = [dossierstatut, syncstatus, syncsourcetype, syncprovidertype]

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Create ENUM types in public schema ──
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ── 2. Create sync_logs table ──
    op.create_table(
        "sync_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Source info
        sa.Column("source_type", syncsourcetype, nullable=False),
        sa.Column("file_name", sa.String(500), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        # Row counters
        sa.Column(
            "rows_total", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "rows_imported", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "rows_updated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "rows_errored", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        # Status
        sa.Column(
            "status",
            syncstatus,
            nullable=False,
            server_default="pending",
        ),
        # Timestamps
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Traceability
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["public.admins.id"],
            ondelete="SET NULL",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_sync_logs_status",
        "sync_logs",
        ["status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_sync_logs_created_at",
        "sync_logs",
        ["created_at"],
        schema=TENANT_SCHEMA,
    )

    # ── 3. Create sync_configs table ──
    op.create_table(
        "sync_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Provider config
        sa.Column(
            "provider_type",
            syncprovidertype,
            nullable=False,
            server_default="excel_csv",
        ),
        sa.Column(
            "config_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "column_mapping",
            postgresql.JSONB(),
            nullable=False,
        ),
        # Scheduling
        sa.Column("schedule_cron", sa.String(100), nullable=True),
        sa.Column("watched_folder", sa.String(500), nullable=True),
        # Status
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_sync_configs_is_active",
        "sync_configs",
        ["is_active"],
        schema=TENANT_SCHEMA,
    )

    # ── 4. Create dossiers table ──
    op.create_table(
        "dossiers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Identification
        sa.Column("numero", sa.String(50), nullable=False),
        # Foreign keys
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Dossier data
        sa.Column(
            "statut",
            dossierstatut,
            nullable=False,
            server_default="en_attente",
        ),
        sa.Column("type_projet", sa.String(200), nullable=True),
        sa.Column("raison_sociale", sa.String(300), nullable=True),
        sa.Column(
            "montant_investissement",
            sa.Numeric(15, 2),
            nullable=True,
        ),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("secteur", sa.String(200), nullable=True),
        sa.Column("date_depot", sa.Date(), nullable=True),
        sa.Column("date_derniere_maj", sa.Date(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            [f"{TENANT_SCHEMA}.contacts.id"],
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_dossiers_numero",
        "dossiers",
        ["numero"],
        unique=True,
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_dossiers_contact_id",
        "dossiers",
        ["contact_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_dossiers_statut",
        "dossiers",
        ["statut"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_dossiers_date_depot",
        "dossiers",
        ["date_depot"],
        schema=TENANT_SCHEMA,
    )

    # ── 5. Create dossier_history table ──
    op.create_table(
        "dossier_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Foreign keys
        sa.Column(
            "dossier_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "sync_log_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Change data
        sa.Column("field_changed", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        # Timestamp
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["dossier_id"],
            [f"{TENANT_SCHEMA}.dossiers.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_log_id"],
            [f"{TENANT_SCHEMA}.sync_logs.id"],
            ondelete="SET NULL",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_dossier_history_dossier_changed",
        "dossier_history",
        ["dossier_id", "changed_at"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    # ── 1. Drop tables (reverse order of creation) ──
    op.drop_table("dossier_history", schema=TENANT_SCHEMA)
    op.drop_table("dossiers", schema=TENANT_SCHEMA)
    op.drop_table("sync_configs", schema=TENANT_SCHEMA)
    op.drop_table("sync_logs", schema=TENANT_SCHEMA)

    # ── 2. Drop ENUM types ──
    bind = op.get_bind()
    for enum in reversed(ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
