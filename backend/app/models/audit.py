"""AuditLog model — immutable audit trail in the PUBLIC schema.

INSERT ONLY: audit records are never updated or deleted.
The application role should only have INSERT + SELECT privileges.
See scripts/apply_audit_policy.sql for production GRANT/REVOKE.

Rétention: 12 mois PostgreSQL, 24 mois archivé sur MinIO (SECURITE.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class AuditLog(UUIDMixin, Base):
    """Journal d'audit immuable pour la traçabilité des actions.

    Réside dans le schéma public pour centraliser les logs
    de tous les tenants. Politique INSERT ONLY pour résister
    aux tentatives d'effacement post-intrusion.

    Note: Does NOT use TimestampMixin because this table is
    immutable — there is no updated_at column.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_tenant", "tenant_slug"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        {"schema": "public"},
    )

    # --- Tenant identity ---
    tenant_slug: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Slug du tenant concerné",
    )

    # --- Actor identity ---
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="ID de l'admin (null pour actions système)",
    )
    user_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Type d'acteur: admin, whatsapp_user, system",
    )

    # --- Action ---
    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Action: create, update, delete, login, logout, export",
    )
    resource_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Type de ressource: contact, kb_document, campaign, etc.",
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="UUID de la ressource affectée",
    )

    # --- HTTP context ---
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        doc="IP du client (IPv4 ou IPv6)",
    )
    user_agent: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        doc="User-Agent du navigateur/client",
    )

    # --- Additional details ---
    details: Mapped[dict | None] = mapped_column(
        JSONB(),
        nullable=True,
        server_default=text("NULL"),
        doc="Infos complémentaires (PAS de PII)",
    )

    # --- Timestamp (immutable — no updated_at) ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action} "
            f"resource={self.resource_type} tenant={self.tenant_slug}>"
        )
