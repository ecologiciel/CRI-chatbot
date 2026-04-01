"""Pydantic v2 schemas for Sync operations (Phase 3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SyncProviderType, SyncSourceType, SyncStatus


# ── SyncLog schemas ──────────────────────────────────────────────


class SyncLogRead(BaseModel):
    """Sync log entry response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: SyncSourceType
    file_name: str | None
    file_hash: str | None
    rows_total: int
    rows_imported: int
    rows_updated: int
    rows_errored: int
    error_details: dict | None
    status: SyncStatus
    started_at: datetime | None
    completed_at: datetime | None
    triggered_by: uuid.UUID | None
    created_at: datetime


class SyncLogList(BaseModel):
    """Paginated list of sync logs."""

    items: list[SyncLogRead]
    total: int
    page: int
    page_size: int


# ── SyncConfig schemas ───────────────────────────────────────────


class SyncConfigCreate(BaseModel):
    """Create a new sync configuration."""

    provider_type: SyncProviderType = SyncProviderType.excel_csv
    config_json: dict = Field(default_factory=dict)
    column_mapping: dict = Field(
        ..., description="Mapping colonne_source → champ_dossier"
    )
    schedule_cron: str | None = Field(
        None, max_length=100, pattern=r"^[\d\s\*\/\-\,]+$"
    )
    watched_folder: str | None = Field(None, max_length=500)
    is_active: bool = True


class SyncConfigUpdate(BaseModel):
    """Update an existing sync configuration (partial)."""

    provider_type: SyncProviderType | None = None
    config_json: dict | None = None
    column_mapping: dict | None = None
    schedule_cron: str | None = None
    watched_folder: str | None = None
    is_active: bool | None = None


class SyncConfigRead(BaseModel):
    """Sync config response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_type: SyncProviderType
    config_json: dict
    column_mapping: dict
    schedule_cron: str | None
    watched_folder: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Import trigger/report schemas ────────────────────────────────


class ImportTriggerRequest(BaseModel):
    """Request to trigger an import manually."""

    file_path: str = Field(
        ..., description="Chemin MinIO du fichier à importer"
    )
    sync_config_id: uuid.UUID | None = Field(
        None, description="Config à utiliser, sinon config active par défaut"
    )


class ImportReportResponse(BaseModel):
    """Result of an import operation."""

    sync_log_id: uuid.UUID
    status: SyncStatus
    rows_total: int
    rows_imported: int
    rows_updated: int
    rows_errored: int
    error_details: dict | None = None
    duration_seconds: float | None = None
