"""Analytics API — period-aware aggregated metrics for the back-office.

All endpoints are tenant-scoped and require at least viewer role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole
from app.schemas.analytics import (
    AnalyticsOverviewResponse,
    LanguageDistribution,
    QuestionTypeDistribution,
    TimeSeriesPoint,
    TopQuestion,
)
from app.schemas.auth import AdminTokenPayload
from app.services.analytics.service import get_analytics_service

router = APIRouter(prefix="/dashboard/analytics", tags=["analytics"])

_ROLES = (
    AdminRole.super_admin,
    AdminRole.admin_tenant,
    AdminRole.supervisor,
    AdminRole.viewer,
)


@router.get("", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> AnalyticsOverviewResponse:
    """Get KPIs with trend comparison vs previous period."""
    service = get_analytics_service()
    data = await service.get_overview(tenant, period, start, end)
    return AnalyticsOverviewResponse(**data)


@router.get("/timeseries", response_model=list[TimeSeriesPoint])
async def get_analytics_timeseries(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> list[TimeSeriesPoint]:
    """Get daily time series for the given period."""
    service = get_analytics_service()
    rows = await service.get_timeseries(tenant, period, start, end)
    return [TimeSeriesPoint(**r) for r in rows]


@router.get("/languages", response_model=list[LanguageDistribution])
async def get_analytics_languages(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> list[LanguageDistribution]:
    """Get conversation count per language."""
    service = get_analytics_service()
    rows = await service.get_languages(tenant, period, start, end)
    return [LanguageDistribution(**r) for r in rows]


@router.get("/question-types", response_model=list[QuestionTypeDistribution])
async def get_analytics_question_types(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> list[QuestionTypeDistribution]:
    """Get conversation breakdown by question type."""
    service = get_analytics_service()
    rows = await service.get_question_types(tenant, period, start, end)
    return [QuestionTypeDistribution(**r) for r in rows]


@router.get("/top-questions", response_model=list[TopQuestion])
async def get_analytics_top_questions(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> list[TopQuestion]:
    """Get top unanswered questions by frequency."""
    service = get_analytics_service()
    rows = await service.get_top_questions(tenant, period, start, end, limit=limit)
    return [TopQuestion(**r) for r in rows]


@router.get("/export/excel")
async def export_analytics_excel(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> StreamingResponse:
    """Export analytics data as an Excel file."""
    service = get_analytics_service()
    buf = await service.export_excel(tenant, period, start, end)
    filename = f"analytics_{period}_{tenant.slug}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/pdf")
async def export_analytics_pdf(
    period: str = Query(default="30d", pattern=r"^(7d|30d|90d|custom)$"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_ROLES)),
) -> StreamingResponse:
    """Export analytics summary as a PDF report."""
    service = get_analytics_service()
    buf = await service.export_pdf(tenant, period, start, end)
    filename = f"analytics_{period}_{tenant.slug}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
