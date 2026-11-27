"""Tenant-scoped, content-free WhatsApp inbox operational visibility.

This staged endpoint requires inbox migrations and is not yet deployed.
"""

from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, literal, select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.enums import AdminRole
from app.models.notification_outbox import NotificationOutboxEvent
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.auth import AdminTokenPayload
from app.schemas.whatsapp import IncomingMessage, StatusInfo
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService

router = APIRouter(prefix="/whatsapp/operations", tags=["whatsapp-operations"])


@router.get("/availability")
async def availability(
    _tenant: TenantContext = Depends(get_current_tenant),
    _admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> dict[str, bool]:
    """Report the intake switch, not worker health or provider connectivity."""
    settings = get_settings()
    return {
        "intake_enabled": settings.whatsapp_durable_inbox_enabled,
        "notification_outbox_enabled": settings.dossier_notification_outbox_enabled,
    }


@router.get("/events")
async def list_events(
    kind: Literal["message", "status", "notification"] = "message",
    state: Literal[
        "pending", "processing", "uncertain", "follow_up", "resolved", "completed", "applied"
    ] = "uncertain",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    tenant: TenantContext = Depends(get_current_tenant),
    _admin: AdminTokenPayload = Depends(
        require_role(AdminRole.super_admin, AdminRole.admin_tenant)
    ),
) -> dict:
    """List metadata only; encrypted content and provider IDs are not exposed."""
    model = {
        "message": WhatsAppInboxEvent,
        "status": WhatsAppStatusEvent,
        "notification": NotificationOutboxEvent,
    }[kind]
    redacted_at = (
        literal(None).label("redacted_at") if kind == "notification" else model.redacted_at
    )
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(
                    model.id,
                    model.state,
                    model.attempts,
                    model.created_at,
                    model.updated_at,
                    redacted_at,
                )
                .where(model.tenant_id == tenant.id, model.state == state)
                .order_by(model.created_at, model.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    return {
        "kind": kind,
        "state": state,
        "offset": offset,
        "events": [
            {
                "id": str(row.id),
                "state": row.state,
                "attempts": row.attempts,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "redacted_at": row.redacted_at,
            }
            for row in rows
        ],
    }


class ReviewRequest(BaseModel):
    action: Literal["follow_up", "resolve"]


@router.get("/events/{event_id}/detail")
async def event_detail(
    event_id: uuid.UUID,
    kind: Literal["message", "status", "notification"] = "message",
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> dict[str, str]:
    """Provide minimal provider identifiers for review, with an audit entry."""
    if kind == "notification":
        async with tenant.db_session() as session:
            event = (
                await session.execute(
                    select(NotificationOutboxEvent)
                    .where(
                        NotificationOutboxEvent.id == event_id,
                        NotificationOutboxEvent.tenant_id == tenant.id,
                    )
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            if event is None:
                raise HTTPException(status_code=404, detail="Événement introuvable")
            recipient = None
            if event.contact_id is not None:
                recipient = (
                    await session.execute(
                        select(Contact.phone).where(Contact.id == event.contact_id)
                    )
                ).scalar_one_or_none()
            session.add(
                AuditLog(
                    tenant_slug=tenant.slug,
                    user_id=uuid.UUID(admin.sub),
                    user_type="admin",
                    action="notif_outbox_view",
                    resource_type="notification_outbox",
                    resource_id=str(event.id),
                    details={"kind": kind},
                )
            )
            await session.flush()
            return {
                "id": str(event.id),
                "state": event.state,
                "provider_message_id": event.provider_message_id or "Non disponible",
                "recipient_masked": "***" + recipient[-4:]
                if recipient and len(recipient) >= 4
                else "***",
                "event_type": event.outcome_code or "Non disponible",
            }
    model = WhatsAppInboxEvent if kind == "message" else WhatsAppStatusEvent
    factory = get_session_factory()
    async with factory() as session:
        event = (
            await session.execute(
                select(model)
                .where(model.id == event_id, model.tenant_id == tenant.id)
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if event is None:
            raise HTTPException(status_code=404, detail="Événement introuvable")
        if event.redacted_at is not None:
            raise HTTPException(
                status_code=410, detail="Détails expirés selon la durée de conservation"
            )
        cipher = VersionedEnvelopeService(factory, get_settings().kms_master_key)
        plaintext = await cipher.decrypt(
            VersionedEnvelope(event.key_version, event.ciphertext),
            tenant_id=tenant.id,
            purpose="wa_inbox" if kind == "message" else "wa_status",
            record_id=event.id,
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict) or payload.get("phone_number_id") != event.phone_number_id:
            raise ValueError("Inbox channel mismatch")
        if kind == "message":
            message = IncomingMessage.model_validate(payload.get("message"))
            if message.id != event.provider_message_id:
                raise ValueError("Inbox message mismatch")
            provider_id, recipient, event_type = message.id, message.from_, message.type
        else:
            status = StatusInfo.model_validate(payload.get("status"))
            provider_id, recipient, event_type = status.id, status.recipient_id, status.status
        session.add(
            AuditLog(
                tenant_slug=tenant.slug,
                user_id=uuid.UUID(admin.sub),
                user_type="admin",
                action="wa_inbox_view",
                resource_type="whatsapp_inbox_event",
                resource_id=str(event.id),
                details={"kind": kind},
            )
        )
        await session.commit()
        return {
            "id": str(event.id),
            "state": event.state,
            "provider_message_id": provider_id,
            "recipient_masked": "***" + recipient[-4:] if len(recipient) >= 4 else "***",
            "event_type": event_type,
        }


@router.post("/events/{event_id}/review")
async def review_event(
    event_id: uuid.UUID,
    data: ReviewRequest,
    kind: Literal["message", "status", "notification"] = "message",
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> dict[str, str]:
    """Record a human review without sending or retrying a message.

    State and immutable audit entry commit together. Resolving is an operator
    decision and is not evidence of provider acceptance or delivery.
    """
    model = {
        "message": WhatsAppInboxEvent,
        "status": WhatsAppStatusEvent,
        "notification": NotificationOutboxEvent,
    }[kind]
    async with get_session_factory()() as session:
        event = (
            await session.execute(
                select(model)
                .where(model.id == event_id, model.tenant_id == tenant.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if event is None:
            raise HTTPException(status_code=404, detail="Événement introuvable")
        allowed = {"uncertain"} if data.action == "follow_up" else {"uncertain", "follow_up"}
        if event.state not in allowed:
            raise HTTPException(status_code=409, detail="État de l’événement modifié")
        previous = event.state
        event.state = "follow_up" if data.action == "follow_up" else "resolved"
        event.updated_at = func.clock_timestamp()
        session.add(
            AuditLog(
                tenant_slug=tenant.slug,
                user_id=uuid.UUID(admin.sub),
                user_type="admin",
                action="notif_outbox_review" if kind == "notification" else "wa_inbox_review",
                resource_type="notification_outbox"
                if kind == "notification"
                else "whatsapp_inbox_event",
                resource_id=str(event.id),
                details={"kind": kind, "previous_state": previous, "decision": data.action},
            )
        )
        await session.commit()
        return {"id": str(event.id), "state": event.state}
