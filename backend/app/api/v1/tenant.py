"""Tenant management API endpoints — CRUD for CRI tenants.

POST and DELETE delegate to TenantProvisioningService (atomic pipeline).
GET and PATCH operate directly on the public.tenants table.
All endpoints are excluded from TenantMiddleware (operate on public schema).
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.exceptions import (
    AuthorizationError,
    CRIEncryptionError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from app.core.minio import get_minio
from app.core.qdrant import get_qdrant
from app.core.rbac import get_current_admin, require_role
from app.core.tenant import TenantResolver
from app.models.audit import AuditLog
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.schemas.auth import AdminTokenPayload
from app.schemas.tenant import (
    TenantAdminResponse,
    TenantCreate,
    TenantList,
    TenantResponse,
    TenantUpdate,
    WhatsAppChannelUpdate,
    WhatsAppConfigView,
)
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.config_envelope import (
    is_sealed_or_malformed,
    load_channel_config,
    prepare_channel_config_write,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/tenants", tags=["tenants"])


async def _admin_view(tenant: Tenant) -> TenantAdminResponse:
    """Expose only allowlisted channel identifiers for either storage format."""
    response = TenantAdminResponse.model_validate(tenant)
    stored = tenant.whatsapp_config
    if isinstance(stored, dict) and is_sealed_or_malformed(stored):
        context = await TenantResolver._build_context(tenant)
        response.whatsapp_config = WhatsAppConfigView.model_validate(context.whatsapp_config)
    return response


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

    return await _admin_view(tenant)


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


@router.get("/health")
async def tenant_resource_health(
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Report resource presence, not end-to-end availability or Meta connectivity."""
    async with get_session_factory()() as session:
        total = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()
        result = await session.execute(
            select(Tenant)
            .order_by(Tenant.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        tenants = list(result.scalars().all())
        schemas = set(
            (await session.execute(text("SELECT nspname FROM pg_catalog.pg_namespace")))
            .scalars()
            .all()
        )

    async def collections():
        try:
            result = await asyncio.wait_for(get_qdrant().get_collections(), timeout=5)
            return {item.name for item in result.collections}
        except Exception as exc:
            logger.warning("tenant_health_qdrant_unavailable", error_type=type(exc).__name__)
            return None

    async def buckets():
        try:
            result = await asyncio.wait_for(get_minio().list_buckets(), timeout=5)
            return {item.name for item in result}
        except Exception as exc:
            logger.warning("tenant_health_minio_unavailable", error_type=type(exc).__name__)
            return None

    collection_names, bucket_names = await asyncio.gather(collections(), buckets())
    items = []
    for tenant in tenants:
        try:
            context = await TenantResolver._build_context(tenant)
            config = context.whatsapp_config or {}
            whatsapp_configured = bool(config.get("phone_number_id") and config.get("access_token"))
        except Exception as exc:
            # A key or database outage is not evidence that the channel is unconfigured.
            logger.warning("tenant_health_whatsapp_unavailable", tenant_id=str(tenant.id), error_type=type(exc).__name__)
            whatsapp_configured = None
        items.append(
            {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "status": tenant.status.value,
                "schema_present": f"tenant_{tenant.slug}" in schemas,
                "collection_present": None
                if collection_names is None
                else f"kb_{tenant.slug}" in collection_names,
                "bucket_present": None
                if bucket_names is None
                else f"cri-{tenant.slug}" in bucket_names,
                "web_enabled": bool((tenant.public_config or {}).get("web_enabled")),
                "whatsapp_configured": whatsapp_configured,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: uuid.UUID,
    admin: AdminTokenPayload = Depends(get_current_admin),
) -> TenantAdminResponse | TenantResponse:
    """Get tenant by ID.

    Access control:
    - super_admin: any tenant → TenantAdminResponse (channel identifiers only)
    - admin_tenant/supervisor/viewer: own tenant only → TenantResponse (no secrets)

    Raises:
        AuthorizationError (403): Cannot access this tenant.
        ResourceNotFoundError (404): Tenant not found.
    """
    # Access control: non-super_admin can only access their own tenant
    is_super_admin = AdminRole(admin.role) == AdminRole.super_admin
    if not is_super_admin and (admin.tenant_id is None or uuid.UUID(admin.tenant_id) != tenant_id):
        raise AuthorizationError(
            "Cannot access this tenant",
            details={"tenant_id": str(tenant_id)},
        )

    # Fetch tenant
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise ResourceNotFoundError(
            f"Tenant not found: {tenant_id}",
            details={"tenant_id": str(tenant_id)},
        )

    # Response type depends on role
    if is_super_admin:
        return await _admin_view(tenant)
    return TenantResponse.model_validate(tenant)


@router.put("/{tenant_id}/whatsapp-channel", response_model=WhatsAppConfigView)
async def update_whatsapp_channel(
    tenant_id: uuid.UUID,
    data: WhatsAppChannelUpdate,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
) -> WhatsAppConfigView:
    """Encrypt credentials and audit their replacement in one transaction."""
    factory = get_session_factory()
    settings = get_settings()
    if not settings.kms_master_key:
        raise CRIEncryptionError("Channel encryption unavailable")
    cipher = VersionedEnvelopeService(factory, settings.kms_master_key)
    async with factory() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if tenant is None:
            raise ResourceNotFoundError("Institution introuvable")
        existing = await load_channel_config(
            tenant_id, tenant.whatsapp_config, cipher, session=session,
            require_encryption=settings.whatsapp_config_require_encryption is True,
        )
        merged = {**(existing or {}), **data.model_dump()}
        tenant.whatsapp_config = await prepare_channel_config_write(
            tenant_id, merged, tenant.whatsapp_config, cipher,
            require_encryption=True, session=session,
        )
        session.add(AuditLog(
            tenant_slug=tenant.slug, user_id=uuid.UUID(admin.sub), user_type="admin",
            action="wa_channel_update", resource_type="tenant", resource_id=str(tenant_id),
            details={"channel": "whatsapp"},
        ))
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if "uq_tenants_whatsapp_phone" in str(exc.orig):
                raise DuplicateResourceError("Cet identifiant WhatsApp est déjà attribué à une institution.") from exc
            raise
    return WhatsAppConfigView(phone_number_id=data.phone_number_id, business_account_id=data.business_account_id)


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
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
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
            if field == "whatsapp_config":
                settings = get_settings()
                previous = tenant.whatsapp_config
                needs_cipher = value is not None and (
                    settings.whatsapp_config_require_encryption is True
                    or (isinstance(previous, dict) and is_sealed_or_malformed(previous))
                )
                cipher = VersionedEnvelopeService(factory, settings.kms_master_key) if needs_cipher and settings.kms_master_key else None
                value = await prepare_channel_config_write(
                    tenant_id, value, previous, cipher,
                    require_encryption=settings.whatsapp_config_require_encryption is True,
                    session=session,
                )
            setattr(tenant, field, value)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if "uq_tenants_whatsapp_phone" in str(exc.orig):
                raise DuplicateResourceError(
                    "Cet identifiant WhatsApp est déjà attribué à une institution."
                ) from exc
            raise
        await session.refresh(tenant)

    logger.info(
        "tenant_updated_via_api",
        tenant_id=str(tenant_id),
        fields=list(update_data.keys()),
        admin_id=admin.sub,
    )

    return await _admin_view(tenant)


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
        result = await session.execute(select(Tenant.slug).where(Tenant.id == tenant_id))
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
    await service.deprovision_tenant(slug, tenant_id=tenant_id)
    return Response(status_code=204)
