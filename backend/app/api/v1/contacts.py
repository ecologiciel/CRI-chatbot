"""Contact management API — CRUD, import Excel/CSV, export.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Static routes (/import, /export) are defined BEFORE /{contact_id} to avoid
FastAPI treating "import"/"export" as UUID path parameters.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pathlib import PurePosixPath

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.core.exceptions import ValidationError
from app.models.enums import AdminRole, Language, OptInStatus
from app.schemas.auth import AdminTokenPayload
from app.schemas.contact import (
    ContactCreate,
    ContactDetailResponse,
    ContactList,
    ContactResponse,
    ContactUpdate,
    ImportResultResponse,
)
from app.services.contact.service import get_contact_service
from app.services.contact.import_export import get_import_export_service

logger = structlog.get_logger()

router = APIRouter(prefix="/contacts", tags=["contacts"])

ALLOWED_IMPORT_EXTENSIONS: set[str] = {".csv", ".xlsx", ".xls"}


# ---------------------------------------------------------------------------
# List contacts
# ---------------------------------------------------------------------------


@router.get("", response_model=ContactList)
async def list_contacts(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        )
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(default=None, description="Search by name, phone, or CIN"),
    opt_in_status: OptInStatus | None = Query(default=None, description="Filter by opt-in status"),
    language: Language | None = Query(default=None, description="Filter by language"),
    tags: str | None = Query(default=None, description="Comma-separated tags"),
) -> ContactList:
    """List contacts with search, filters, and pagination."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    service = get_contact_service()
    items, total = await service.list_contacts(
        tenant,
        page=page,
        page_size=page_size,
        search=search,
        opt_in_status=opt_in_status,
        language=language,
        tags=tag_list,
    )

    return ContactList(
        items=[ContactResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Import contacts (BEFORE /{contact_id})
# ---------------------------------------------------------------------------


@router.post("/import", response_model=ImportResultResponse)
async def import_contacts(
    file: UploadFile,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> ImportResultResponse:
    """Import contacts from an Excel or CSV file.

    Deduplicates by phone number. Max 50,000 rows.
    """
    log = logger.bind(tenant=tenant.slug, admin_id=admin.sub, filename=file.filename)

    # Validate extension
    ext = PurePosixPath(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMPORT_EXTENSIONS:
        raise ValidationError(
            f"Format non supporté: {ext}. Utilisez .csv ou .xlsx",
            details={"extension": ext, "allowed": sorted(ALLOWED_IMPORT_EXTENSIONS)},
        )

    file_bytes = await file.read()
    service = get_import_export_service()
    result = await service.import_contacts(tenant, file_bytes, file.filename or "import.csv")

    log.info(
        "import_completed",
        created=result.created,
        skipped=result.skipped,
        errors=len(result.errors),
    )
    return ImportResultResponse(
        created=result.created,
        skipped=result.skipped,
        errors=result.errors,
    )


# ---------------------------------------------------------------------------
# Export contacts (BEFORE /{contact_id})
# ---------------------------------------------------------------------------


@router.get("/export")
async def export_contacts(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        )
    ),
    format: str = Query(default="csv", pattern=r"^(csv|xlsx)$", description="Export format"),
) -> StreamingResponse:
    """Export all contacts as Excel or CSV file."""
    service = get_import_export_service()

    if format == "xlsx":
        content = await service.export_to_xlsx(tenant)
        return StreamingResponse(
            iter([content]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=contacts_{tenant.slug}.xlsx"},
        )

    content = await service.export_to_csv(tenant)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=contacts_{tenant.slug}.csv"},
    )


# ---------------------------------------------------------------------------
# Create contact
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=ContactResponse)
async def create_contact(
    data: ContactCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> ContactResponse:
    """Create a new contact manually."""
    service = get_contact_service()
    contact = await service.create_contact(tenant, data)
    return ContactResponse.model_validate(contact)


# ---------------------------------------------------------------------------
# Get contact detail
# ---------------------------------------------------------------------------


@router.get("/{contact_id}", response_model=ContactDetailResponse)
async def get_contact(
    contact_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
        )
    ),
) -> ContactDetailResponse:
    """Get contact detail with conversation count and last interaction."""
    service = get_contact_service()
    contact, conversation_count, last_interaction = await service.get_contact_detail(
        tenant, contact_id,
    )
    response = ContactDetailResponse.model_validate(contact)
    response.conversation_count = conversation_count
    response.last_interaction = last_interaction
    return response


# ---------------------------------------------------------------------------
# Update contact
# ---------------------------------------------------------------------------


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> ContactResponse:
    """Update contact (tags, name, opt_in_status, etc.)."""
    service = get_contact_service()
    contact = await service.update_contact(tenant, contact_id, data)
    return ContactResponse.model_validate(contact)


# ---------------------------------------------------------------------------
# Delete contact
# ---------------------------------------------------------------------------


@router.delete("/{contact_id}", status_code=204, response_class=Response)
async def delete_contact(
    contact_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> Response:
    """Delete a contact and cascade to conversations/messages."""
    service = get_contact_service()
    await service.delete_contact(tenant, contact_id)
    return Response(status_code=204)
