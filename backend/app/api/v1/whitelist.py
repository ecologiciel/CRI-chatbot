"""Internal agent whitelist API — CRUD for authorized phone numbers.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Static route (/check) is defined BEFORE /{entry_id} to avoid FastAPI treating
"check" as a UUID path parameter.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole
from app.models.whitelist import InternalWhitelist
from app.schemas.auth import AdminTokenPayload
from app.schemas.whitelist import (
    InternalWhitelistCreate,
    InternalWhitelistList,
    InternalWhitelistResponse,
    InternalWhitelistUpdate,
    WhitelistCheckResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/whitelist", tags=["whitelist"])


# ---------------------------------------------------------------------------
# List whitelist entries
# ---------------------------------------------------------------------------


@router.get("", response_model=InternalWhitelistList)
async def list_whitelist(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(default=None, description="Search by phone or label"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
) -> InternalWhitelistList:
    """List whitelisted phone numbers with optional search and filters."""
    async with tenant.db_session() as session:
        base = select(InternalWhitelist)

        if is_active is not None:
            base = base.where(InternalWhitelist.is_active == is_active)

        if search:
            pattern = f"%{search}%"
            base = base.where(
                InternalWhitelist.phone.ilike(pattern)
                | InternalWhitelist.label.ilike(pattern)
            )

        total_q = select(func.count()).select_from(base.subquery())
        total = (await session.execute(total_q)).scalar_one()

        items_q = (
            base.order_by(InternalWhitelist.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await session.execute(items_q)).scalars().all())

    return InternalWhitelistList(
        items=[InternalWhitelistResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Check if phone is whitelisted (BEFORE /{entry_id})
# ---------------------------------------------------------------------------


@router.get("/check", response_model=WhitelistCheckResponse)
async def check_whitelist(
    phone: str = Query(..., description="Phone number in E.164 format"),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> WhitelistCheckResponse:
    """Check whether a phone number is whitelisted and active."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(InternalWhitelist).where(
                InternalWhitelist.phone == phone,
                InternalWhitelist.is_active.is_(True),
            )
        )
        entry = result.scalar_one_or_none()

    return WhitelistCheckResponse(phone=phone, is_whitelisted=entry is not None)


# ---------------------------------------------------------------------------
# Create whitelist entry
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=InternalWhitelistResponse)
async def create_whitelist_entry(
    data: InternalWhitelistCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> InternalWhitelistResponse:
    """Add a phone number to the internal agent whitelist.

    The phone must be in E.164 format (+212612345678).
    409 if the phone is already whitelisted for this tenant.
    """
    async with tenant.db_session() as session:
        existing = (
            await session.execute(
                select(InternalWhitelist).where(
                    InternalWhitelist.phone == data.phone
                )
            )
        ).scalar_one_or_none()

        if existing:
            raise DuplicateResourceError(
                "Phone already whitelisted",
                details={"phone": data.phone},
            )

        entry = InternalWhitelist(
            phone=data.phone,
            label=data.label,
            note=data.note,
            is_active=True,
            added_by=uuid.UUID(admin.sub),
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)

    logger.info(
        "whitelist_entry_created",
        tenant=tenant.slug,
        phone=data.phone,
        admin_id=admin.sub,
    )
    return InternalWhitelistResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Update whitelist entry
# ---------------------------------------------------------------------------


@router.patch("/{entry_id}", response_model=InternalWhitelistResponse)
async def update_whitelist_entry(
    entry_id: uuid.UUID,
    data: InternalWhitelistUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> InternalWhitelistResponse:
    """Update label, note, or active status of a whitelist entry."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(InternalWhitelist).where(InternalWhitelist.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            raise ResourceNotFoundError(
                f"Whitelist entry {entry_id} not found",
                details={"entry_id": str(entry_id)},
            )

        update_fields = data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(entry, field, value)

        await session.flush()
        await session.refresh(entry)

    return InternalWhitelistResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Delete whitelist entry
# ---------------------------------------------------------------------------


@router.delete("/{entry_id}", status_code=204, response_class=Response)
async def delete_whitelist_entry(
    entry_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> Response:
    """Permanently delete a phone number from the whitelist."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(InternalWhitelist).where(InternalWhitelist.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            raise ResourceNotFoundError(
                f"Whitelist entry {entry_id} not found",
                details={"entry_id": str(entry_id)},
            )

        await session.delete(entry)
        await session.flush()

    logger.info(
        "whitelist_entry_deleted",
        tenant=tenant.slug,
        entry_id=str(entry_id),
        admin_id=admin.sub,
    )
    return Response(status_code=204)
