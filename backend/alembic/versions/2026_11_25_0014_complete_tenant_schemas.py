"""Add missing tenant tables without replacing existing tenant data.

Revision ID: 0014
Revises: 0013
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "contacts",
    "kb_documents",
    "incentive_categories",
    "conversations",
    "messages",
    "kb_chunks",
    "incentive_items",
    "feedback",
    "unanswered_questions",
    "campaigns",
    "campaign_recipients",
    "escalations",
    "internal_whitelist",
    "dossiers",
    "sync_configs",
    "sync_logs",
    "dossier_history",
    "rag_evaluation_cases",
    "rag_evaluation_runs",
)

# Each FK belongs to the first table; existing tables are left untouched.
FKS = (
    ("conversations", "fk_conv_contact", "contact_id", None, "contacts", "CASCADE"),
    ("messages", "fk_msg_conversation", "conversation_id", None, "conversations", "CASCADE"),
    ("kb_chunks", "fk_chunk_document", "document_id", None, "kb_documents", "CASCADE"),
    ("feedback", "fk_feedback_message", "message_id", None, "messages", "CASCADE"),
    (
        "incentive_categories",
        "fk_category_parent",
        "parent_id",
        None,
        "incentive_categories",
        "CASCADE",
    ),
    ("incentive_items", "fk_item_category", "category_id", None, "incentive_categories", "CASCADE"),
    ("unanswered_questions", "fk_uq_reviewer", "reviewed_by", "public", "admins", "SET NULL"),
    ("campaigns", "fk_campaign_creator", "created_by", "public", "admins", "NO ACTION"),
    ("campaign_recipients", "fk_recip_campaign", "campaign_id", None, "campaigns", "CASCADE"),
    ("campaign_recipients", "fk_recip_contact", "contact_id", None, "contacts", "NO ACTION"),
    ("escalations", "fk_escalation_conv", "conversation_id", None, "conversations", "CASCADE"),
    ("escalations", "fk_escalation_assignee", "assigned_to", "public", "admins", "SET NULL"),
    ("internal_whitelist", "fk_whitelist_creator", "added_by", "public", "admins", "SET NULL"),
    ("dossiers", "fk_dossier_contact", "contact_id", None, "contacts", "NO ACTION"),
    ("sync_logs", "fk_sync_trigger", "triggered_by", "public", "admins", "SET NULL"),
    ("dossier_history", "fk_history_dossier", "dossier_id", None, "dossiers", "CASCADE"),
    ("dossier_history", "fk_history_sync", "sync_log_id", None, "sync_logs", "SET NULL"),
)


def upgrade() -> None:
    bind = op.get_bind()
    quote = bind.dialect.identifier_preparer.quote
    slugs = bind.execute(sa.text("SELECT slug FROM public.tenants ORDER BY slug")).scalars()
    for slug in slugs:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", slug):
            raise ValueError("Invalid tenant slug in database")
        schema = f"tenant_{slug}"
        if schema == "tenant_template" or len(schema) > 63:
            raise ValueError("Tenant schema collision or invalid length")
        if not bind.execute(
            sa.text("SELECT to_regnamespace(:name) IS NOT NULL"), {"name": schema}
        ).scalar_one():
            raise RuntimeError(f"Missing tenant schema: {schema}")
        created = set()
        for table in TABLES:
            exists = bind.execute(
                sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{schema}.{table}"}
            ).scalar_one()
            if not exists:
                op.execute(
                    sa.text(
                        f"CREATE TABLE {quote(schema)}.{quote(table)} (LIKE tenant_template.{quote(table)} INCLUDING ALL)"
                    )
                )
                created.add(table)
        for table, name, column, target_schema, target_table, on_delete in FKS:
            if table in created:
                ref_schema = target_schema or schema
                op.execute(
                    sa.text(
                        f"ALTER TABLE {quote(schema)}.{quote(table)} ADD CONSTRAINT {quote(name)} "
                        f"FOREIGN KEY ({quote(column)}) REFERENCES {quote(ref_schema)}.{quote(target_table)}(id) "
                        f"ON DELETE {on_delete}"
                    )
                )


def downgrade() -> None:
    raise RuntimeError("Restoring the previous schema requires a verified backup")
