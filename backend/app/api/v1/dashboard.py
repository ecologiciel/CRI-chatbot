"""Dashboard API — aggregated KPIs for the back-office.

Single endpoint returning all dashboard statistics in one call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload
from app.schemas.dashboard import DashboardStatsResponse
from app.services.dashboard.service import get_dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        )
    ),
) -> DashboardStatsResponse:
    """Get aggregated dashboard KPIs for the current tenant."""
    service = get_dashboard_service()
    stats = await service.get_stats(tenant)
    return DashboardStatsResponse(**stats)
