"""create phase 1 tables

Revision ID: 002
Revises: 001
Create Date: 2026-03-25

Creates:
- admins table in public schema
- tenant_template schema with: contacts, conversations, messages,
  kb_documents, kb_chunks, feedback, unanswered_questions
- All required ENUM types in public schema
- All indexes including GIN and partial unique
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── ENUM types (all in public schema, shared across tenants) ──

language = postgresql.ENUM(
    "fr", "ar", "en",
    name="language", schema="public", create_type=False,
)
optinstatus = postgresql.ENUM(
    "opted_in", "opted_out", "pending",
    name="optinstatus", schema="public", create_type=False,
)
contactsource = postgresql.ENUM(
    "whatsapp", "import_csv", "manual",
    name="contactsource", schema="public", create_type=False,
)
agenttype = postgresql.ENUM(
    "public", "internal",
    name="agenttype", schema="public", create_type=False,
)
conversationstatus = postgresql.ENUM(
    "active", "ended", "escalated", "human_handled",
    name="conversationstatus", schema="public", create_type=False,
)
messagedirection = postgresql.ENUM(
    "inbound", "outbound",
    name="messagedirection", schema="public", create_type=False,
)
messagetype = postgresql.ENUM(
    "text", "image", "audio", "document", "interactive", "system",
    name="messagetype", schema="public", create_type=False,
)
adminrole = postgresql.ENUM(
    "super_admin", "admin_tenant", "supervisor", "viewer",
    name="adminrole", schema="public", create_type=False,
)
kbdocumentstatus = postgresql.ENUM(
    "pending", "indexing", "indexed", "error",
    name="kbdocumentstatus", schema="public", create_type=False,
)
feedbackrating = postgresql.ENUM(
    "positive", "negative", "question",
    name="feedbackrating", schema="public", create_type=False,
)
unansweredstatus = postgresql.ENUM(
    "pending", "approved", "modified", "rejected", "injected",
    name="unansweredstatus", schema="public", create_type=False,
)

ALL_ENUMS = [
    language, optinstatus, contactsource, agenttype, conversationstatus,
    messagedirection, messagetype, adminrole, kbdocumentstatus,
    feedbackrating, unansweredstatus,
]

TENANT_SCHEMA = "tenant_template"


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Create ENUM types ──
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ── 2. Create tenant_template schema ──
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {TENANT_SCHEMA}")

    # ── 3. Create admins table (public schema) ──
    op.create_table(
        "admins",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role", adminrole,
            server_default="viewer", nullable=False,
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "is_active", sa.Boolean(),
            server_default=sa.text("true"), nullable=False,
        ),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["public.tenants.id"], ondelete="SET NULL",
        ),
        schema="public",
    )
    op.create_index("ix_admins_email", "admins", ["email"], unique=True, schema="public")
    op.create_index("ix_admins_tenant_id", "admins", ["tenant_id"], schema="public")
    op.create_index("ix_admins_role", "admins", ["role"], schema="public")

    # ── 4. Create contacts table (tenant_template) ──
    op.create_table(
        "contacts",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("language", language, server_default="fr", nullable=False),
        sa.Column("cin", sa.String(20), nullable=True),
        sa.Column("opt_in_status", optinstatus, server_default="pending", nullable=False),
        sa.Column("tags", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source", contactsource, server_default="whatsapp", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_contacts_phone", "contacts", ["phone"], unique=True, schema=TENANT_SCHEMA,
    )
    op.create_index("ix_contacts_cin", "contacts", ["cin"], schema=TENANT_SCHEMA)
    op.create_index(
        "ix_contacts_tags", "contacts", ["tags"],
        schema=TENANT_SCHEMA, postgresql_using="gin",
    )
    op.create_index(
        "ix_contacts_created_at", "contacts", ["created_at"], schema=TENANT_SCHEMA,
    )

    # ── 5. Create conversations table (tenant_template) ──
    op.create_table(
        "conversations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", agenttype, server_default="public", nullable=False),
        sa.Column("status", conversationstatus, server_default="active", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["contact_id"], [f"{TENANT_SCHEMA}.contacts.id"], ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_conversations_contact_id", "conversations", ["contact_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_conversations_status", "conversations", ["status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_conversations_started_at", "conversations", ["started_at"],
        schema=TENANT_SCHEMA,
    )

    # ── 6. Create messages table (tenant_template) ──
    op.create_table(
        "messages",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", messagedirection, nullable=False),
        sa.Column("type", messagetype, server_default="text", nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("media_url", sa.String(500), nullable=True),
        sa.Column(
            "chunk_ids", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False,
        ),
        sa.Column("whatsapp_message_id", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], [f"{TENANT_SCHEMA}.conversations.id"],
            ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_messages_whatsapp_message_id", "messages", ["whatsapp_message_id"],
        unique=True, schema=TENANT_SCHEMA,
        postgresql_where=sa.text("whatsapp_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_messages_timestamp", "messages", ["timestamp"],
        schema=TENANT_SCHEMA,
    )

    # ── 7. Create kb_documents table (tenant_template) ──
    op.create_table(
        "kb_documents",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("language", sa.String(5), server_default="fr", nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", kbdocumentstatus, server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_documents_category", "kb_documents", ["category"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_documents_status", "kb_documents", ["status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_documents_content_hash", "kb_documents", ["content_hash"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_documents_created_at", "kb_documents", ["created_at"],
        schema=TENANT_SCHEMA,
    )

    # ── 8. Create kb_chunks table (tenant_template) ──
    op.create_table(
        "kb_chunks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(100), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_doc_index"),
        sa.ForeignKeyConstraint(
            ["document_id"], [f"{TENANT_SCHEMA}.kb_documents.id"],
            ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_chunks_document_id", "kb_chunks", ["document_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_kb_chunks_qdrant_point_id", "kb_chunks", ["qdrant_point_id"],
        schema=TENANT_SCHEMA,
    )

    # ── 9. Create feedback table (tenant_template) ──
    op.create_table(
        "feedback",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", feedbackrating, nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "chunk_ids", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["message_id"], [f"{TENANT_SCHEMA}.messages.id"],
            ondelete="CASCADE",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_feedback_message_id", "feedback", ["message_id"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_feedback_rating", "feedback", ["rating"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_feedback_created_at", "feedback", ["created_at"],
        schema=TENANT_SCHEMA,
    )

    # ── 10. Create unanswered_questions table (tenant_template) ──
    op.create_table(
        "unanswered_questions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("language", sa.String(5), server_default="fr", nullable=False),
        sa.Column("frequency", sa.Integer(), server_default="1", nullable=False),
        sa.Column("proposed_answer", sa.Text(), nullable=True),
        sa.Column("status", unansweredstatus, server_default="pending", nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["public.admins.id"], ondelete="SET NULL",
        ),
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_unanswered_questions_status", "unanswered_questions", ["status"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_unanswered_questions_status_freq", "unanswered_questions",
        ["status", "frequency"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_unanswered_questions_language", "unanswered_questions", ["language"],
        schema=TENANT_SCHEMA,
    )
    op.create_index(
        "ix_unanswered_questions_created_at", "unanswered_questions", ["created_at"],
        schema=TENANT_SCHEMA,
    )


def downgrade() -> None:
    # ── Drop tenant_template tables and schema ──
    op.drop_table("unanswered_questions", schema=TENANT_SCHEMA)
    op.drop_table("feedback", schema=TENANT_SCHEMA)
    op.drop_table("kb_chunks", schema=TENANT_SCHEMA)
    op.drop_table("kb_documents", schema=TENANT_SCHEMA)
    op.drop_table("messages", schema=TENANT_SCHEMA)
    op.drop_table("conversations", schema=TENANT_SCHEMA)
    op.drop_table("contacts", schema=TENANT_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {TENANT_SCHEMA} CASCADE")

    # ── Drop admins table ──
    op.drop_table("admins", schema="public")

    # ── Drop ENUM types ──
    bind = op.get_bind()
    for enum in reversed(ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
