"""Pydantic v2 schemas for Dossier tracking (Phase 3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DossierStatut


# ── Dossier schemas ──────────────────────────────────────────────


class DossierCreate(BaseModel):
    """For programmatic import (not a public creation API)."""

    numero: str = Field(..., max_length=50)
    contact_id: uuid.UUID | None = None
    statut: DossierStatut = DossierStatut.en_attente
    type_projet: str | None = Field(None, max_length=200)
    raison_sociale: str | None = Field(None, max_length=300)
    montant_investissement: Decimal | None = Field(None, ge=0)
    region: str | None = Field(None, max_length=100)
    secteur: str | None = Field(None, max_length=200)
    date_depot: date | None = None
    date_derniere_maj: date | None = None
    observations: str | None = None
    raw_data: dict | None = None


class DossierRead(BaseModel):
    """Dossier response — list view (no history)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    contact_id: uuid.UUID | None
    statut: DossierStatut
    type_projet: str | None
    raison_sociale: str | None
    montant_investissement: Decimal | None
    region: str | None
    secteur: str | None
    date_depot: date | None
    date_derniere_maj: date | None
    observations: str | None
    created_at: datetime
    updated_at: datetime


class DossierHistoryRead(BaseModel):
    """Single history entry for a dossier field change."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_changed: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime
    sync_log_id: uuid.UUID | None


class DossierDetail(DossierRead):
    """Dossier detail response — includes full history."""

    history: list[DossierHistoryRead] = []


class DossierList(BaseModel):
    """Paginated list of dossiers."""

    items: list[DossierRead]
    total: int
    page: int
    page_size: int


class DossierStats(BaseModel):
    """Aggregated KPIs for back-office and Agent Interne."""

    total: int = 0
    en_cours: int = 0
    valide: int = 0
    rejete: int = 0
    en_attente: int = 0
    incomplet: int = 0


class DossierFilters(BaseModel):
    """Filters for paginated dossier listing."""

    statut: DossierStatut | None = None
    type_projet: str | None = None
    date_depot_from: date | None = None
    date_depot_to: date | None = None
    search: str | None = None  # search on numero, raison_sociale
