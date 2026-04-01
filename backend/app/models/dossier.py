"""Dossier and DossierHistory models — stored in the TENANT schema.

A dossier represents an investment project file tracked by the CRI.
DossierHistory is an append-only audit trail of field-level changes,
correlated with sync operations via sync_log_id.

Phase 3: dossier tracking, OTP authentication, Excel/CSV import.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import DossierStatut

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.sync import SyncLog


class Dossier(UUIDMixin, TimestampMixin, Base):
    """Dossier d'investissement suivi par le CRI.

    Importé depuis le SI du CRI via Excel/CSV ou API REST.
    Chaque dossier est lié à un contact (investisseur) et
    possède un historique de modifications.

    Attributes:
        numero: Numéro unique du dossier (format CRI).
        contact_id: Investisseur associé (nullable).
        statut: Statut courant du dossier.
        type_projet: Type de projet d'investissement.
        raison_sociale: Raison sociale de l'entreprise.
        montant_investissement: Montant en MAD.
        region: Région du projet.
        secteur: Secteur d'activité.
        date_depot: Date de dépôt du dossier.
        date_derniere_maj: Date de dernière mise à jour SI.
        observations: Notes libres.
        raw_data: Données Excel originales non mappées.
    """

    __tablename__ = "dossiers"
    __table_args__ = (
        Index("ix_dossiers_numero", "numero", unique=True),
        Index("ix_dossiers_contact_id", "contact_id"),
        Index("ix_dossiers_statut", "statut"),
        Index("ix_dossiers_date_depot", "date_depot"),
    )

    # ── Identification ────────────────────────────────────────────
    numero: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
    )

    # ── Foreign keys ──────────────────────────────────────────────
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id"),
        nullable=True,
    )

    # ── Dossier data ──────────────────────────────────────────────
    statut: Mapped[DossierStatut] = mapped_column(
        Enum(DossierStatut, name="dossierstatut", schema="public"),
        nullable=False,
        default=DossierStatut.en_attente,
        server_default=DossierStatut.en_attente.value,
    )
    type_projet: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    raison_sociale: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )
    montant_investissement: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2),
        nullable=True,
    )
    region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    secteur: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    date_depot: Mapped[datetime | None] = mapped_column(
        Date,
        nullable=True,
    )
    date_derniere_maj: Mapped[datetime | None] = mapped_column(
        Date,
        nullable=True,
    )
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Relationships ─────────────────────────────────────────────
    contact: Mapped[Contact | None] = relationship(
        lazy="selectin",
    )
    history: Mapped[list[DossierHistory]] = relationship(
        back_populates="dossier",
        cascade="all, delete-orphan",
        order_by="DossierHistory.changed_at.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<Dossier id={self.id} "
            f"numero={self.numero!r} "
            f"statut={self.statut.value}>"
        )


class DossierHistory(UUIDMixin, Base):
    """Historique des modifications d'un dossier — append-only.

    Chaque entrée trace un changement de champ, avec l'ancienne
    et la nouvelle valeur. Corrélé à un sync_log si le changement
    provient d'un import.

    Attributes:
        dossier_id: Dossier concerné.
        field_changed: Nom du champ modifié.
        old_value: Ancienne valeur (texte).
        new_value: Nouvelle valeur (texte).
        changed_at: Horodatage du changement.
        sync_log_id: Import ayant causé le changement (nullable).
    """

    __tablename__ = "dossier_history"
    __table_args__ = (
        Index(
            "ix_dossier_history_dossier_changed",
            "dossier_id",
            "changed_at",
        ),
    )

    # ── Foreign keys ──────────────────────────────────────────────
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dossiers.id", ondelete="CASCADE"),
        nullable=False,
    )
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sync_logs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Change data ───────────────────────────────────────────────
    field_changed: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamp (append-only — no updated_at) ──────────────────
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────
    dossier: Mapped[Dossier] = relationship(
        back_populates="history",
    )
    sync_log: Mapped[SyncLog | None] = relationship(
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<DossierHistory id={self.id} "
            f"field={self.field_changed!r} "
            f"dossier_id={self.dossier_id}>"
        )
