"""Tenant-scoped, content-free WhatsApp inbox operational visibility.

This staged endpoint requires inbox migrations and is not yet deployed.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.auth import AdminTokenPayload

router = APIRouter(prefix="/whatsapp/operations", tags=["whatsapp-operations"])


@router.get("/events")
async def list_events(
    kind: Literal["message", "status"] = "message",
    state: Literal["pending", "processing", "uncertain", "completed", "applied"] = "uncertain",
    limit: int = Query(default=50, ge=1, le=100),
    tenant: TenantContext = Depends(get_current_tenant),
    _admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> dict:
    """List metadata only; encrypted content and provider IDs are not exposed."""
    model = WhatsAppInboxEvent if kind == "message" else WhatsAppStatusEvent
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(model.id, model.state, model.attempts, model.created_at, model.updated_at)
                .where(model.tenant_id == tenant.id, model.state == state)
                .order_by(model.created_at, model.id)
                .limit(limit)
            )
        ).all()
    return {
        "kind": kind,
        "state": state,
        "events": [
            {
                "id": str(row.id),
                "state": row.state,
                "attempts": row.attempts,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ],
    }
