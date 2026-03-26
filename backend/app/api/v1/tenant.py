"""Tenant management API endpoints — CRUD for CRI tenants.

POST and DELETE delegate to TenantProvisioningService (atomic pipeline).
GET and PATCH operate directly on the public.tenants table.
All endpoints are excluded from TenantMiddleware (operate on public schema).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.core.exceptions import AuthorizationError, ResourceNotFoundError
from app.core.rbac import get_current_admin, require_role
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.schemas.auth import AdminTokenPayload
from app.schemas.tenant import (
    TenantAdminResponse,
    TenantCreate,
    TenantList,
    TenantResponse,
    TenantUpdate,
)
from app.services.tenant.provisioning import TenantProvisioningService

logger = structlog.get_logger()

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("/", response_model=TenantAdminResponse, status_code=201)
async def create_tenant(
    data: TenantCreate,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
) -> TenantAdminResponse:
    """Provision a new tenant (super_admin only).

    Atomic pipeline: DB record → PG schema → Qdrant collection →
    Redis mapping → MinIO bucket → activate. Auto-rollback on failure.

    Raises:
        DuplicateTenantError (409): Slug already exists.
        TenantProvisioningError (500): Pipeline failure.
    """
    service = TenantProvisioningService()
    tenant = await service.provision_tenant(data)

    logger.info(
        "tenant_created_via_api",
        tenant_id=str(tenant.id),
        slug=tenant.slug,
        admin_id=admin.sub,
    )

    return TenantAdminResponse.model_validate(tenant)


@router.get("/", response_model=TenantList)
async def list_tenants(
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: TenantStatus | None = Query(default=None, description="Filter by status"),
) -> TenantList:
    """List all tenants with pagination (super_admin only).

    Args:
        page: Page number (1-indexed).
        page_size: Items per page (max 100).
        status: Optional status filter (active, inactive, provisioning).
    """
    factory = get_session_factory()
    async with factory() as session:
        # Count query
        count_stmt = select(func.count(Tenant.id))
        if status is not None:
            count_stmt = count_stmt.where(Tenant.status == status)
        total = (await session.execute(count_stmt)).scalar_one()

        # Data query
        data_stmt = select(Tenant).order_by(Tenant.created_at.desc())
        if status is not None:
            data_stmt = data_stmt.where(Tenant.status == status)
        data_stmt = data_stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(data_stmt)
        tenants = result.scalars().all()

    return TenantList(
        items=[TenantResponse.model_validate(t) for t in tenants],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: uuid.UUID,
    admin: AdminTokenPayload = Depends(get_current_admin),
) -> TenantAdminResponse | TenantResponse:
    """Get tenant by ID.

    Access control:
    - super_admin: any tenant → TenantAdminResponse (includes whatsapp_config)
    - admin_tenant/supervisor/viewer: own tenant only → TenantResponse (no secrets)

    Raises:
        AuthorizationError (403): Cannot access this tenant.
        ResourceNotFoundError (404): Tenant not found.
    """
    # Access control: non-super_admin can only access their own tenant
    is_super_admin = AdminRole(admin.role) == AdminRole.super_admin
    if not is_super_admin:
        if admin.tenant_id is None or uuid.UUID(admin.tenant_id) != tenant_id:
            raise AuthorizationError(
                "Cannot access this tenant",
                details={"tenant_id": str(tenant_id)},
            )

    # Fetch tenant
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise ResourceNotFoundError(
            f"Tenant not found: {tenant_id}",
            details={"tenant_id": str(tenant_id)},
        )

    # Response type depends on role
    if is_super_admin:
        return TenantAdminResponse.model_validate(tenant)
    return TenantResponse.model_validate(tenant)


@router.patch("/{tenant_id}", response_model=TenantAdminResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
) -> TenantAdminResponse:
    """Update tenant fields (super_admin only).

    Partial update: only explicitly provided fields are modified.
    Use model_dump(exclude_unset=True) to distinguish between
    "not sent" and "explicitly set to None".

    Raises:
        ResourceNotFoundError (404): Tenant not found.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise ResourceNotFoundError(
                f"Tenant not found: {tenant_id}",
                details={"tenant_id": str(tenant_id)},
            )

        # Apply partial update
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            # Convert WhatsAppConfig Pydantic model to dict for JSONB column
            if field == "whatsapp_config" and value is not None and hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(tenant, field, value)

        await session.commit()
        await session.refresh(tenant)

    logger.info(
        "tenant_updated_via_api",
        tenant_id=str(tenant_id),
        fields=list(update_data.keys()),
        admin_id=admin.sub,
    )

    return TenantAdminResponse.model_validate(tenant)


@router.delete("/{tenant_id}", status_code=204, response_class=Response)
async def delete_tenant(
    tenant_id: uuid.UUID,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
) -> Response:
    """Deprovision a tenant and delete all resources (super_admin only).

    DANGEROUS: removes PG schema, Qdrant collection, MinIO bucket,
    Redis mappings, and the tenant record. Best-effort cleanup
    (continues on partial failure).

    Raises:
        ResourceNotFoundError (404): Tenant not found.
    """
    # Resolve slug from ID (deprovision_tenant takes slug)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Tenant.slug).where(Tenant.id == tenant_id)
        )
        slug = result.scalar_one_or_none()

    if not slug:
        raise ResourceNotFoundError(
            f"Tenant not found: {tenant_id}",
            details={"tenant_id": str(tenant_id)},
        )

    logger.warning(
        "tenant_deletion_initiated",
        tenant_id=str(tenant_id),
        slug=slug,
        admin_id=admin.sub,
    )

    service = TenantProvisioningService()
    await service.deprovision_tenant(slug)
    return Response(status_code=204)
