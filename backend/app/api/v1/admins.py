"""Admin management API — CRUD for tenant administrators.

All endpoints operate on public.admins (NOT tenant-scoped).
Tenant filtering is done via the caller's JWT tenant_id.
Routes under /auth/admins are auto-excluded from TenantMiddleware
(prefix /api/v1/auth/ in TENANT_EXCLUDED_PREFIXES).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.core.exceptions import (
    AuthorizationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.rbac import require_role
from app.models.admin import Admin
from app.models.enums import AdminRole
from app.schemas.admin import AdminCreate, AdminList, AdminResponse, AdminUpdate
from app.schemas.auth import AdminTokenPayload
from app.services.auth.service import AuthService

logger = structlog.get_logger()

router = APIRouter(prefix="/auth/admins", tags=["admin-management"])

MAX_ADMINS_PER_TENANT = 10


# ---------------------------------------------------------------------------
# List admins for caller's tenant
# ---------------------------------------------------------------------------


@router.get("", response_model=AdminList)
async def list_admins(
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(default=None, description="Search by email or name"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
    tenant_id: uuid.UUID | None = Query(
        default=None, description="Tenant filter (super_admin only)"
    ),
) -> AdminList:
    """List administrators for the caller's tenant.

    Super-admins may pass tenant_id to view any tenant's admins.
    Non-super-admins are restricted to their own tenant.
    """
    effective_tenant_id = _resolve_tenant_id(admin, tenant_id)

    factory = get_session_factory()
    async with factory() as session:
        base = select(Admin).where(Admin.tenant_id == effective_tenant_id)

        if is_active is not None:
            base = base.where(Admin.is_active == is_active)

        if search:
            pattern = f"%{search}%"
            base = base.where(Admin.email.ilike(pattern) | Admin.full_name.ilike(pattern))

        total_q = select(func.count()).select_from(base.subquery())
        total = (await session.execute(total_q)).scalar_one()

        items_q = (
            base.order_by(Admin.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = list((await session.execute(items_q)).scalars().all())

    return AdminList(
        items=[AdminResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Create admin
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=AdminResponse)
async def create_admin(
    data: AdminCreate,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> AdminResponse:
    """Create a new administrator for the caller's tenant.

    Enforces max 10 admins per tenant. Non-super-admins can only
    create supervisor or viewer roles within their own tenant.

    Raises:
        ValidationError: Max admin limit reached or invalid role.
        DuplicateResourceError: Email already in use.
    """
    effective_tenant_id = _resolve_tenant_id(admin, data.tenant_id)

    # Role restriction: admin_tenant cannot create admin_tenant or super_admin
    if admin.role != AdminRole.super_admin.value and data.role in (
        AdminRole.super_admin,
        AdminRole.admin_tenant,
    ):
        raise AuthorizationError("Only super_admin can create admin_tenant or super_admin roles")

    factory = get_session_factory()
    async with factory() as session:
        # Enforce max 10 per tenant
        count_q = select(func.count()).where(
            Admin.tenant_id == effective_tenant_id,
            Admin.is_active.is_(True),
        )
        active_count = (await session.execute(count_q)).scalar_one()

        if active_count >= MAX_ADMINS_PER_TENANT:
            raise ValidationError(
                f"Maximum {MAX_ADMINS_PER_TENANT} active administrators per tenant",
                details={"current_count": active_count, "limit": MAX_ADMINS_PER_TENANT},
            )

        # Check email uniqueness
        existing = (
            await session.execute(select(Admin).where(Admin.email == data.email.lower()))
        ).scalar_one_or_none()

        if existing:
            raise DuplicateResourceError(
                "An admin with this email already exists",
                details={"email": data.email},
            )

        new_admin = Admin(
            email=data.email.lower(),
            password_hash=AuthService.hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            tenant_id=effective_tenant_id,
            is_active=True,
        )
        session.add(new_admin)
        await session.flush()
        await session.refresh(new_admin)
        result = AdminResponse.model_validate(new_admin)
        await session.commit()

    logger.info(
        "admin_created",
        new_admin_id=str(result.id),
        email=data.email,
        role=data.role.value,
        tenant_id=str(effective_tenant_id),
        created_by=admin.sub,
    )
    return result


# ---------------------------------------------------------------------------
# Update admin
# ---------------------------------------------------------------------------


@router.patch("/{admin_id}", response_model=AdminResponse)
async def update_admin(
    admin_id: uuid.UUID,
    data: AdminUpdate,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> AdminResponse:
    """Update an administrator's profile (role, name, active status).

    Self-deactivation is blocked. Non-super-admins cannot promote
    to admin_tenant or super_admin.

    Raises:
        ResourceNotFoundError: Admin not found in caller's tenant.
        ValidationError: Self-deactivation attempt.
        AuthorizationError: Insufficient privileges for role change.
    """
    # Self-deactivation guard
    if str(admin_id) == admin.sub and data.is_active is False:
        raise ValidationError("Cannot deactivate your own account")

    # Role escalation guard
    if (
        admin.role != AdminRole.super_admin.value
        and data.role is not None
        and data.role in (AdminRole.super_admin, AdminRole.admin_tenant)
    ):
        raise AuthorizationError("Only super_admin can assign admin_tenant or super_admin roles")

    factory = get_session_factory()
    async with factory() as session:
        target = await _get_admin_in_tenant(session, admin_id, admin)

        update_fields = data.model_dump(exclude_unset=True)
        # Non-super-admins cannot change tenant_id
        if admin.role != AdminRole.super_admin.value:
            update_fields.pop("tenant_id", None)

        for field, value in update_fields.items():
            setattr(target, field, value)

        await session.flush()
        await session.refresh(target)
        result = AdminResponse.model_validate(target)
        await session.commit()

    logger.info(
        "admin_updated",
        admin_id=str(admin_id),
        updated_fields=list(update_fields.keys()),
        updated_by=admin.sub,
    )
    return result


# ---------------------------------------------------------------------------
# Deactivate (soft-delete) admin
# ---------------------------------------------------------------------------


@router.delete("/{admin_id}", status_code=204, response_class=Response)
async def deactivate_admin(
    admin_id: uuid.UUID,
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> Response:
    """Soft-deactivate an administrator (sets is_active=False).

    Raises:
        ValidationError: Self-deactivation attempt.
        ResourceNotFoundError: Admin not found in caller's tenant.
    """
    if str(admin_id) == admin.sub:
        raise ValidationError("Cannot deactivate your own account")

    factory = get_session_factory()
    async with factory() as session:
        target = await _get_admin_in_tenant(session, admin_id, admin)
        target.is_active = False
        await session.flush()
        await session.commit()

    logger.info(
        "admin_deactivated",
        admin_id=str(admin_id),
        deactivated_by=admin.sub,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_tenant_id(
    admin: AdminTokenPayload, requested_tenant_id: uuid.UUID | None
) -> uuid.UUID:
    """Resolve effective tenant_id from JWT and optional override.

    Super-admins may target any tenant. Other roles are locked to
    their own tenant_id from the JWT.
    """
    if admin.role == AdminRole.super_admin.value:
        if requested_tenant_id is not None:
            return requested_tenant_id
        if admin.tenant_id is not None:
            return uuid.UUID(admin.tenant_id)
        raise ValidationError("super_admin must specify tenant_id")

    if admin.tenant_id is None:
        raise ValidationError("Admin JWT missing tenant_id")

    return uuid.UUID(admin.tenant_id)


async def _get_admin_in_tenant(session, admin_id: uuid.UUID, caller: AdminTokenPayload) -> Admin:
    """Fetch an admin by ID and verify tenant ownership.

    Super-admins bypass tenant check.
    """
    result = await session.execute(select(Admin).where(Admin.id == admin_id))
    target = result.scalar_one_or_none()

    if target is None:
        raise ResourceNotFoundError(
            f"Admin {admin_id} not found",
            details={"admin_id": str(admin_id)},
        )

    # Non-super-admins can only manage admins in their own tenant
    if caller.role != AdminRole.super_admin.value and str(target.tenant_id) != caller.tenant_id:
        raise ResourceNotFoundError(
            f"Admin {admin_id} not found",
            details={"admin_id": str(admin_id)},
        )

    return target
