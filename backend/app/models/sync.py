"""SyncLog and SyncConfig models — stored in the TENANT schema.

SyncLog tracks each data synchronisation operation (Excel/CSV import,
API pull, manual entry).  SyncConfig stores reusable import configurations
with column mappings, cron schedules, and MinIO watched folders.

Phase 3: SI integration level 1 (Excel/CSV) + level 2 (API REST).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import SyncProviderType, SyncSourceType, SyncStatus

if TYPE_CHECKING:
    from app.models.admin import Admin


class SyncLog(UUIDMixin, Base):
    """Journal d'une opération de synchronisation — append-only.

    Chaque import (Excel, CSV, API) crée une entrée SyncLog qui
    suit le cycle : pending → running → completed/failed.
    Les erreurs par ligne sont stockées dans error_details (JSONB).

    Attributes:
        source_type: Type de source (excel, csv, api_rest, manual).
        file_name: Nom du fichier importé (nullable pour API/manual).
        file_hash: SHA-256 du fichier pour détecter les doublons.
        rows_total: Nombre total de lignes dans le fichier.
        rows_imported: Lignes créées avec succès.
        rows_updated: Lignes mises à jour (dossier existant).
        rows_errored: Lignes en erreur.
        error_details: Détails des erreurs par ligne (JSONB).
        status: Statut courant de l'opération.
        started_at: Début du traitement.
        completed_at: Fin du traitement.
        triggered_by: Admin ayant déclenché l'import (nullable pour cron).
    """

    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_status", "status"),
        Index("ix_sync_logs_created_at", "created_at"),
    )

    # ── Source info ───────────────────────────────────────────────
    source_type: Mapped[SyncSourceType] = mapped_column(
        Enum(SyncSourceType, name="syncsourcetype", schema="public"),
        nullable=False,
    )
    file_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # ── Row counters ──────────────────────────────────────────────
    rows_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    rows_imported: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    rows_updated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    rows_errored: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    error_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Status ────────────────────────────────────────────────────
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="syncstatus", schema="public"),
        nullable=False,
        default=SyncStatus.pending,
        server_default=SyncStatus.pending.value,
    )

    # ── Timestamps ────────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Traceability ──────────────────────────────────────────────
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.admins.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Timestamp (no TimestampMixin — log table, no updated_at) ─
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────
    triggered_by_admin: Mapped[Admin | None] = relationship(
        foreign_keys=[triggered_by],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<SyncLog id={self.id} "
            f"source={self.source_type.value} "
            f"status={self.status.value}>"
        )


class SyncConfig(UUIDMixin, TimestampMixin, Base):
    """Configuration d'import réutilisable pour un tenant.

    Stocke le mapping colonne Excel/CSV → champ dossier,
    le cron schedule pour les imports automatiques, et le
    dossier MinIO à surveiller.

    Attributes:
        provider_type: Type de fournisseur SI (excel_csv, api_rest, db_link).
        config_json: Configuration technique du provider (JSONB).
        column_mapping: Mapping colonne_source → champ_dossier.
        schedule_cron: Expression cron pour import auto (nullable).
        watched_folder: Chemin MinIO à surveiller (nullable).
        is_active: Configuration active ou non.
    """

    __tablename__ = "sync_configs"
    __table_args__ = (
        Index("ix_sync_configs_is_active", "is_active"),
    )

    # ── Provider config ───────────────────────────────────────────
    provider_type: Mapped[SyncProviderType] = mapped_column(
        Enum(SyncProviderType, name="syncprovidertype", schema="public"),
        nullable=False,
        default=SyncProviderType.excel_csv,
        server_default=SyncProviderType.excel_csv.value,
    )
    config_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    column_mapping: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    # ── Scheduling ────────────────────────────────────────────────
    schedule_cron: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    watched_folder: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # ── Status ────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    def __repr__(self) -> str:
        return (
            f"<SyncConfig id={self.id} "
            f"provider={self.provider_type.value} "
            f"active={self.is_active}>"
        )
