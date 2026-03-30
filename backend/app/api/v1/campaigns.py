"""Campaign management API — CRUD, lifecycle, stats, recipients.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
Static route (/quota) is defined BEFORE /{campaign_id} to avoid FastAPI treating
"quota" as a UUID path parameter.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.exceptions import ValidationError
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.campaign import Campaign
from app.models.enums import AdminRole, CampaignStatus, RecipientStatus
from app.schemas.auth import AdminTokenPayload
from app.schemas.campaign import (
    AudiencePreview,
    CampaignCreate,
    CampaignList,
    CampaignRead,
    CampaignSchedule,
    CampaignStats,
    CampaignUpdate,
    RecipientList,
    RecipientRead,
)
from app.services.campaign import get_campaign_service

logger = structlog.get_logger()

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ---------------------------------------------------------------------------
# List campaigns
# ---------------------------------------------------------------------------


@router.get("", response_model=CampaignList)
async def list_campaigns(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: CampaignStatus | None = Query(default=None, description="Filter by status"),
) -> CampaignList:
    """List campaigns with optional status filter, newest first."""
    service = get_campaign_service()
    items, total = await service.list_campaigns(
        tenant,
        page=page,
        page_size=page_size,
        status=status,
    )
    return CampaignList(
        items=[CampaignRead.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Create campaign
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=CampaignRead)
async def create_campaign(
    data: CampaignCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Create a new campaign in draft status."""
    service = get_campaign_service()
    campaign = await service.create_campaign(
        tenant,
        data,
        uuid.UUID(admin.sub),
    )
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Quota status (BEFORE /{campaign_id})
# ---------------------------------------------------------------------------


@router.get("/quota")
async def get_quota_status(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
    count: int = Query(default=0, ge=0, description="Number of messages to check against quota"),
) -> dict:
    """Check tenant WhatsApp quota: used, limit, remaining, percentage."""
    service = get_campaign_service()
    return await service.check_quota(tenant, count)


# ---------------------------------------------------------------------------
# Get campaign detail
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Get campaign details by ID."""
    service = get_campaign_service()
    campaign = await service.get_campaign(tenant, campaign_id)
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Update campaign (draft only)
# ---------------------------------------------------------------------------


@router.patch("/{campaign_id}", response_model=CampaignRead)
async def update_campaign(
    campaign_id: uuid.UUID,
    data: CampaignUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Update a campaign. Only draft campaigns can be edited (400 otherwise)."""
    service = get_campaign_service()
    campaign = await service.update_campaign(
        tenant,
        campaign_id,
        data,
        uuid.UUID(admin.sub),
    )
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Schedule campaign
# ---------------------------------------------------------------------------


@router.post("/{campaign_id}/schedule", response_model=CampaignRead)
async def schedule_campaign(
    campaign_id: uuid.UUID,
    body: CampaignSchedule,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Schedule a draft campaign for future sending. 400 if not draft."""
    service = get_campaign_service()
    campaign = await service.get_campaign(tenant, campaign_id)

    if campaign.status != CampaignStatus.draft:
        raise ValidationError(
            "Only draft campaigns can be scheduled",
            details={"current_status": campaign.status.value},
        )

    async with tenant.db_session() as session:
        result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
        db_campaign = result.scalar_one()
        db_campaign.scheduled_at = body.scheduled_at
        db_campaign.status = CampaignStatus.scheduled
        await session.flush()
        await session.refresh(db_campaign)

    logger.info(
        "campaign_scheduled",
        tenant=tenant.slug,
        campaign_id=str(campaign_id),
        scheduled_at=str(body.scheduled_at),
    )
    return CampaignRead.model_validate(db_campaign)


# ---------------------------------------------------------------------------
# Launch campaign
# ---------------------------------------------------------------------------


@router.post("/{campaign_id}/launch", response_model=CampaignRead)
async def launch_campaign(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Launch a campaign. Verifies quota before sending. 400 if not draft/scheduled."""
    service = get_campaign_service()
    campaign = await service.launch_campaign(
        tenant,
        campaign_id,
        uuid.UUID(admin.sub),
    )
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Pause campaign
# ---------------------------------------------------------------------------


@router.post("/{campaign_id}/pause", response_model=CampaignRead)
async def pause_campaign(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Pause a campaign that is currently sending. 400 if not sending."""
    service = get_campaign_service()
    campaign = await service.pause_campaign(
        tenant,
        campaign_id,
        uuid.UUID(admin.sub),
    )
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Resume campaign
# ---------------------------------------------------------------------------


@router.post("/{campaign_id}/resume", response_model=CampaignRead)
async def resume_campaign(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignRead:
    """Resume a paused campaign. 400 if not paused."""
    service = get_campaign_service()
    campaign = await service.resume_campaign(
        tenant,
        campaign_id,
        uuid.UUID(admin.sub),
    )
    return CampaignRead.model_validate(campaign)


# ---------------------------------------------------------------------------
# Campaign stats
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> CampaignStats:
    """Real-time delivery statistics: sent, delivered, read, failed, rates."""
    service = get_campaign_service()
    return await service.get_campaign_stats(tenant, campaign_id)


# ---------------------------------------------------------------------------
# Campaign recipients
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}/recipients", response_model=RecipientList)
async def list_recipients(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    status: RecipientStatus | None = Query(default=None, description="Filter by delivery status"),
) -> RecipientList:
    """List campaign recipients with optional status filter."""
    service = get_campaign_service()
    items, total = await service.get_recipients(
        tenant,
        campaign_id,
        page=page,
        page_size=page_size,
        status=status,
    )
    return RecipientList(
        items=[RecipientRead.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Audience preview
# ---------------------------------------------------------------------------


@router.post("/{campaign_id}/preview", response_model=AudiencePreview)
async def preview_audience(
    campaign_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> AudiencePreview:
    """Preview the audience for a campaign (count + sample of 5 contacts)."""
    service = get_campaign_service()
    campaign = await service.get_campaign(tenant, campaign_id)
    return await service.preview_audience(tenant, campaign.audience_filter)
