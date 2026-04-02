"""Dossier management API — list, detail, import, sync logs, sync configs.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Static routes (/stats, /import, /sync-logs, /sync-configs) are defined BEFORE
/{dossier_id} to avoid FastAPI treating those paths as UUID parameters.

Wave 25A — Phase 3.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from pathlib import PurePosixPath

import structlog
from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.arq import get_arq_pool
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.minio import get_minio
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.dossier import Dossier
from app.models.enums import AdminRole, DossierStatut, SyncStatus
from app.models.sync import SyncConfig, SyncLog
from app.schemas.auth import AdminTokenPayload
from app.schemas.dossier import (
    DossierDetail,
    DossierFilters,
    DossierList,
    DossierStats,
)
from app.schemas.sync import (
    SyncConfigCreate,
    SyncConfigRead,
    SyncConfigUpdate,
    SyncLogList,
    SyncLogRead,
)
from app.services.dossier.service import get_dossier_service

logger = structlog.get_logger()

router = APIRouter(prefix="/dossiers", tags=["Dossiers"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_IMPORT_SIZE = 10 * 1024 * 1024  # 10 MB

CONTENT_TYPE_MAP: dict[str, str] = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}


# ---------------------------------------------------------------------------
# Endpoint 1 — List dossiers (paginated + filters)
# ---------------------------------------------------------------------------


@router.get("", response_model=DossierList)
async def list_dossiers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    statut: DossierStatut | None = Query(default=None),
    type_projet: str | None = Query(default=None),
    date_depot_from: date | None = Query(default=None),
    date_depot_to: date | None = Query(default=None),
    search: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant, AdminRole.supervisor)
    ),
) -> DossierList:
    """List dossiers with pagination and optional filters."""
    filters = DossierFilters(
        statut=statut,
        type_projet=type_projet,
        date_depot_from=date_depot_from,
        date_depot_to=date_depot_to,
        search=search,
    )
    service = get_dossier_service()
    return await service.list_dossiers(
        tenant, filters=filters, page=page, page_size=page_size
    )


# ---------------------------------------------------------------------------
# Endpoint 2 — Dossier stats (KPI aggregates)
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=DossierStats)
async def get_dossier_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant, AdminRole.supervisor)
    ),
) -> DossierStats:
    """Get aggregated dossier KPIs for the current tenant."""
    service = get_dossier_service()
    return await service.get_dossier_stats(tenant)


# ---------------------------------------------------------------------------
# Endpoint 3 — Import dossiers (upload file → MinIO → ARQ)
# ---------------------------------------------------------------------------


@router.post("/import", status_code=202)
async def import_dossiers(
    file: UploadFile,
    sync_config_id: uuid.UUID | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> dict:
    """Upload a dossier file and enqueue an import task.

    Stores the file in MinIO and enqueues an ARQ worker task
    for background processing. Returns 202 Accepted.
    """
    log = logger.bind(tenant=tenant.slug, admin_id=admin.sub, filename=file.filename)

    # 1. Validate extension
    ext = PurePosixPath(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Format non supporté: {ext}. Utilisez .xlsx, .xls ou .csv",
            details={"extension": ext, "allowed": sorted(ALLOWED_EXTENSIONS)},
        )

    # 2. Read and validate size
    file_bytes = await file.read()
    if len(file_bytes) > MAX_IMPORT_SIZE:
        raise ValidationError(
            f"Fichier trop volumineux: {len(file_bytes)} octets (max 10 MB)",
            details={"file_size": len(file_bytes), "max_size": MAX_IMPORT_SIZE},
        )

    # 3. Upload to MinIO
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_name = PurePosixPath(file.filename or "import").name
    object_path = f"imports/pending/{timestamp}_{safe_name}"
    content_type = CONTENT_TYPE_MAP.get(ext, "application/octet-stream")

    minio = get_minio()
    await minio.put_object(
        bucket_name=tenant.minio_bucket,
        object_name=object_path,
        data=io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type=content_type,
    )

    # 4. Enqueue ARQ task
    pool = get_arq_pool()
    await pool.enqueue_job(
        "task_import_dossier",
        object_path,
        str(sync_config_id) if sync_config_id else None,
        tenant.slug,
        admin.sub,
    )

    log.info(
        "import_enqueued",
        file_path=object_path,
        file_size=len(file_bytes),
        sync_config_id=str(sync_config_id) if sync_config_id else None,
    )

    return {"message": "Import accepté", "file_path": object_path}


# ---------------------------------------------------------------------------
# Endpoint 4 — List sync logs (paginated)
# ---------------------------------------------------------------------------


@router.get("/sync-logs", response_model=SyncLogList)
async def list_sync_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: SyncStatus | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> SyncLogList:
    """List sync logs with pagination and optional status filter."""
    async with tenant.db_session() as session:
        # Count query
        count_stmt = select(func.count(SyncLog.id))
        if status is not None:
            count_stmt = count_stmt.where(SyncLog.status == status)
        total = (await session.execute(count_stmt)).scalar_one()

        # Data query
        data_stmt = (
            select(SyncLog)
            .order_by(SyncLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if status is not None:
            data_stmt = data_stmt.where(SyncLog.status == status)

        rows = (await session.execute(data_stmt)).scalars().all()

    return SyncLogList(
        items=[SyncLogRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Endpoint 5 — Sync log detail
# ---------------------------------------------------------------------------


@router.get("/sync-logs/{sync_log_id}", response_model=SyncLogRead)
async def get_sync_log(
    sync_log_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> SyncLogRead:
    """Get a single sync log entry by ID."""
    async with tenant.db_session() as session:
        row = await session.get(SyncLog, sync_log_id)

    if row is None:
        raise ResourceNotFoundError(
            f"Sync log introuvable: {sync_log_id}",
            details={"sync_log_id": str(sync_log_id)},
        )
    return SyncLogRead.model_validate(row)


# ---------------------------------------------------------------------------
# Endpoint 6 — List sync configs
# ---------------------------------------------------------------------------


@router.get("/sync-configs", response_model=list[SyncConfigRead])
async def list_sync_configs(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> list[SyncConfigRead]:
    """List all sync configurations for the current tenant."""
    async with tenant.db_session() as session:
        rows = (
            await session.execute(
                select(SyncConfig).order_by(SyncConfig.created_at.desc())
            )
        ).scalars().all()

    return [SyncConfigRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Endpoint 7 — Create sync config
# ---------------------------------------------------------------------------


@router.post("/sync-configs", status_code=201, response_model=SyncConfigRead)
async def create_sync_config(
    data: SyncConfigCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> SyncConfigRead:
    """Create a new sync configuration."""
    log = logger.bind(tenant=tenant.slug, admin_id=admin.sub)

    async with tenant.db_session() as session:
        config = SyncConfig(
            provider_type=data.provider_type,
            config_json=data.config_json,
            column_mapping=data.column_mapping,
            schedule_cron=data.schedule_cron,
            watched_folder=data.watched_folder,
            is_active=data.is_active,
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)
        result = SyncConfigRead.model_validate(config)

    log.info("sync_config_created", config_id=str(result.id))
    return result


# ---------------------------------------------------------------------------
# Endpoint 8 — Update sync config (partial)
# ---------------------------------------------------------------------------


@router.put("/sync-configs/{config_id}", response_model=SyncConfigRead)
async def update_sync_config(
    config_id: uuid.UUID,
    data: SyncConfigUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> SyncConfigRead:
    """Update an existing sync configuration (partial update)."""
    async with tenant.db_session() as session:
        config = await session.get(SyncConfig, config_id)
        if config is None:
            raise ResourceNotFoundError(
                f"Sync config introuvable: {config_id}",
                details={"config_id": str(config_id)},
            )

        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(config, field, value)

        await session.flush()
        await session.refresh(config)
        result = SyncConfigRead.model_validate(config)

    logger.bind(tenant=tenant.slug).info(
        "sync_config_updated", config_id=str(config_id), fields=list(updates.keys())
    )
    return result


# ---------------------------------------------------------------------------
# Endpoint 9 — Dossier detail (LAST — dynamic catch-all)
# ---------------------------------------------------------------------------


@router.get("/{dossier_id}", response_model=DossierDetail)
async def get_dossier(
    dossier_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant, AdminRole.supervisor)
    ),
) -> DossierDetail:
    """Get dossier detail including full change history."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(Dossier)
            .where(Dossier.id == dossier_id)
            .options(selectinload(Dossier.history))
        )
        dossier = result.scalar_one_or_none()

    if dossier is None:
        raise ResourceNotFoundError(
            f"Dossier introuvable: {dossier_id}",
            details={"dossier_id": str(dossier_id)},
        )
    return DossierDetail.model_validate(dossier)
