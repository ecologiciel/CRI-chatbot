"""Notification management API — history, stats, manual send, templates.

All notification history lives in ``public.audit_logs`` with
``resource_type='notification'``.  Templates are stored in the
``_EVENT_TEMPLATE_MAP`` constant with per-tenant overrides in
``tenants.whatsapp_config['notification_templates']``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text

from app.core.database import get_session_factory
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.rbac import require_role
from app.core.redis import get_redis
from app.core.tenant import TenantContext, TenantResolver, get_current_tenant
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.dossier import Dossier
from app.models.enums import AdminRole, OptInStatus
from app.models.tenant import Tenant
from app.schemas.audit import AuditLogCreate
from app.schemas.auth import AdminTokenPayload
from app.schemas.notification import (
    ManualNotificationRequest,
    ManualNotificationResponse,
    NotificationHistoryItem,
    NotificationHistoryList,
    NotificationStats,
    NotificationTemplateRead,
    NotificationTemplateUpdate,
    audit_action_to_status,
)
from app.services.audit.service import get_audit_service
from app.services.notification.service import (
    NotificationEventType,
    NotificationPriority,
    _EVENT_TEMPLATE_MAP,
    get_notification_service,
)
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

router = APIRouter(prefix="/notifications", tags=["notifications"])

# ── RBAC role sets ──────────────────────────────────────────────────

_READ_ROLES = (AdminRole.supervisor, AdminRole.admin_tenant, AdminRole.super_admin)
_WRITE_ROLES = (AdminRole.admin_tenant, AdminRole.super_admin)

# ── Status mapping ──────────────────────────────────────────────────

_STATUS_TO_ACTION: dict[str, str] = {
    "sent": "notification_sent",
    "skipped": "notification_skipped",
    "failed": "notification_failed",
}

# ── Template descriptions ───────────────────────────────────────────

_EVENT_DESCRIPTIONS: dict[str, str] = {
    "decision_finale": "Decision finale (validation/rejet) d'un dossier",
    "complement_request": "Demande de complement de dossier",
    "status_update": "Mise a jour du statut du dossier",
    "dossier_incomplet": "Notification de dossier incomplet",
}

_EVENT_DEFAULT_PRIORITIES: dict[str, str] = {
    "decision_finale": NotificationPriority.high.value,
    "complement_request": NotificationPriority.high.value,
    "status_update": NotificationPriority.medium.value,
    "dossier_incomplet": NotificationPriority.low.value,
}


# ── Helpers ─────────────────────────────────────────────────────────


def _audit_log_to_history_item(log: AuditLog) -> NotificationHistoryItem:
    """Convert an AuditLog ORM row to a NotificationHistoryItem."""
    details = log.details or {}
    return NotificationHistoryItem(
        id=log.id,
        event_type=details.get("event_type"),
        status=audit_action_to_status(log.action),
        contact_id=details.get("contact_id"),
        dossier_id=log.resource_id,
        dossier_numero=details.get("numero"),
        template_name=details.get("template"),
        wamid=details.get("wamid"),
        reason=details.get("reason"),
        created_at=log.created_at,
    )


def _build_template_list(
    tenant: TenantContext,
) -> list[NotificationTemplateRead]:
    """Build the list of notification templates with tenant overrides."""
    overrides: dict[str, str] = {}
    if tenant.whatsapp_config:
        overrides = tenant.whatsapp_config.get("notification_templates", {})

    templates: list[NotificationTemplateRead] = []
    for event_type, default_name in _EVENT_TEMPLATE_MAP.items():
        templates.append(
            NotificationTemplateRead(
                event_type=event_type.value,
                template_name=overrides.get(event_type.value, default_name),
                description=_EVENT_DESCRIPTIONS.get(event_type.value, ""),
                priority=_EVENT_DEFAULT_PRIORITIES.get(
                    event_type.value, NotificationPriority.medium.value
                ),
            )
        )
    return templates


# ── Endpoint 1: GET /notifications — Paginated history ─────────────


@router.get("", response_model=NotificationHistoryList)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, pattern=r"^(sent|skipped|failed)$"),
    event_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_READ_ROLES)),
) -> NotificationHistoryList:
    """Return paginated notification history for the current tenant."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))

        base = select(AuditLog).where(
            AuditLog.tenant_slug == tenant.slug,
            AuditLog.resource_type == "notification",
        )

        if status:
            base = base.where(AuditLog.action == _STATUS_TO_ACTION[status])
        if event_type:
            base = base.where(
                AuditLog.details["event_type"].as_string() == event_type,
            )
        if date_from:
            base = base.where(AuditLog.created_at >= date_from)
        if date_to:
            base = base.where(AuditLog.created_at <= date_to)

        # Count
        count_result = await session.execute(
            select(func.count()).select_from(base.subquery()),
        )
        total = count_result.scalar_one()

        # Paginated data
        offset = (page - 1) * page_size
        data_result = await session.execute(
            base.order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(page_size),
        )
        logs = list(data_result.scalars().all())

    return NotificationHistoryList(
        items=[_audit_log_to_history_item(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── Endpoint 2: GET /notifications/stats — Aggregated stats ────────


@router.get("/stats", response_model=NotificationStats)
async def get_notification_stats(
    days: int = Query(default=30, ge=1, le=365),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_READ_ROLES)),
) -> NotificationStats:
    """Return aggregated notification statistics for the current tenant."""
    since = datetime.now(UTC) - timedelta(days=days)

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))

        base_where = [
            AuditLog.tenant_slug == tenant.slug,
            AuditLog.resource_type == "notification",
            AuditLog.created_at >= since,
        ]

        # Counts by action
        action_rows = await session.execute(
            select(AuditLog.action, func.count())
            .where(*base_where)
            .group_by(AuditLog.action),
        )
        action_counts: dict[str, int] = {}
        for action, cnt in action_rows:
            action_counts[action] = cnt

        # Counts by event_type (from JSONB)
        event_rows = await session.execute(
            select(
                AuditLog.details["event_type"].as_string(),
                func.count(),
            )
            .where(*base_where)
            .group_by(AuditLog.details["event_type"].as_string()),
        )
        by_event_type: dict[str, int] = {}
        for evt, cnt in event_rows:
            if evt:
                by_event_type[evt] = cnt

    return NotificationStats(
        total_sent=action_counts.get("notification_sent", 0)
        + action_counts.get("notif_manual_sent", 0),
        total_skipped=action_counts.get("notification_skipped", 0),
        total_failed=action_counts.get("notification_failed", 0),
        by_event_type=by_event_type,
        period_days=days,
    )


# ── Endpoint 3: POST /notifications/send — Manual send ─────────────


@router.post("/send", response_model=ManualNotificationResponse)
async def send_manual_notification(
    data: ManualNotificationRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> ManualNotificationResponse:
    """Manually send a notification to a contact."""
    log = logger.bind(
        tenant=tenant.slug,
        admin_id=admin.sub,
        contact_id=str(data.contact_id),
    )

    # 1. Load contact
    async with tenant.db_session() as session:
        result = await session.execute(
            select(Contact).where(Contact.id == data.contact_id),
        )
        contact = result.scalar_one_or_none()

    if not contact:
        raise ResourceNotFoundError(
            f"Contact not found: {data.contact_id}",
            details={"contact_id": str(data.contact_id)},
        )

    # 2. Load dossier
    async with tenant.db_session() as session:
        result = await session.execute(
            select(Dossier).where(Dossier.id == data.dossier_id),
        )
        dossier = result.scalar_one_or_none()

    if not dossier:
        raise ResourceNotFoundError(
            f"Dossier not found: {data.dossier_id}",
            details={"dossier_id": str(data.dossier_id)},
        )

    # 3. Opt-in check (CNDP compliance)
    if contact.opt_in_status == OptInStatus.opted_out:
        log.info("manual_send_skipped_optout", contact_id=str(data.contact_id))
        return ManualNotificationResponse(status="skipped", reason="opted_out")

    # 4. Phone check
    if not contact.phone:
        log.info("manual_send_skipped_no_phone", contact_id=str(data.contact_id))
        return ManualNotificationResponse(status="skipped", reason="no_phone")

    # 5. Resolve template
    event_type = NotificationEventType(data.event_type)
    service = get_notification_service()
    template_name = service.get_template_name(event_type)

    # Check tenant override
    if tenant.whatsapp_config:
        overrides = tenant.whatsapp_config.get("notification_templates", {})
        template_name = overrides.get(data.event_type, template_name)

    # 6. Build template components
    language_code = contact.language.value if contact.language else "fr"
    components = service.build_template_components(
        contact_name=contact.name or "Investisseur",
        dossier_numero=dossier.numero,
        event_type=event_type,
        language_code=language_code,
    )

    # 7. Send via WhatsApp
    sender = WhatsAppSenderService()
    try:
        wamid = await sender.send_template(
            tenant=tenant,
            to=contact.phone,
            template_name=template_name,
            language_code=language_code,
            components=components,
        )
    except Exception as exc:
        log.error("manual_send_failed", error=str(exc), exc_info=True)
        await get_audit_service().log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=uuid.UUID(admin.sub),
                user_type="admin",
                action="notification_failed",
                resource_type="notification",
                resource_id=str(data.dossier_id),
                details={
                    "event_type": data.event_type,
                    "contact_id": str(data.contact_id),
                    "error": str(exc),
                    "manual": True,
                },
            ),
        )
        return ManualNotificationResponse(status="failed", reason=str(exc))

    # 8. Audit trail
    log.info("manual_send_success", wamid=wamid)
    await get_audit_service().log_action(
        AuditLogCreate(
            tenant_slug=tenant.slug,
            user_id=uuid.UUID(admin.sub),
            user_type="admin",
            action="notif_manual_sent",
            resource_type="notification",
            resource_id=str(data.dossier_id),
            details={
                "event_type": data.event_type,
                "contact_id": str(data.contact_id),
                "template": template_name,
                "wamid": wamid,
                "numero": dossier.numero,
            },
        ),
    )

    return ManualNotificationResponse(status="sent", wamid=wamid)


# ── Endpoint 4: GET /notifications/templates — List templates ───────


@router.get("/templates", response_model=list[NotificationTemplateRead])
async def list_templates(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_READ_ROLES)),
) -> list[NotificationTemplateRead]:
    """Return the notification template mappings for the current tenant."""
    return _build_template_list(tenant)


# ── Endpoint 5: PUT /notifications/templates/{event_type} ──────────


@router.put(
    "/templates/{event_type}",
    response_model=NotificationTemplateRead,
)
async def update_template(
    event_type: str,
    data: NotificationTemplateUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> NotificationTemplateRead:
    """Update the Meta template name for a notification event type."""
    # Validate event_type
    try:
        NotificationEventType(event_type)
    except ValueError as err:
        valid = sorted(e.value for e in NotificationEventType)
        raise ValidationError(
            f"Invalid event_type '{event_type}'. Must be one of: {valid}",
            details={"event_type": event_type, "valid": valid},
        ) from err

    # Update whatsapp_config in public.tenants
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(select(Tenant).where(Tenant.id == tenant.id))
        tenant_row = result.scalar_one()

        config = dict(tenant_row.whatsapp_config or {})
        notif_templates = dict(config.get("notification_templates", {}))
        notif_templates[event_type] = data.template_name
        config["notification_templates"] = notif_templates
        tenant_row.whatsapp_config = config
        await session.commit()

    # Invalidate Redis tenant cache
    redis = get_redis()
    cache_key = f"{TenantResolver.REDIS_TENANT_CACHE_PREFIX}:{tenant.id}"
    await redis.delete(cache_key)

    # Audit trail
    await get_audit_service().log_action(
        AuditLogCreate(
            tenant_slug=tenant.slug,
            user_id=uuid.UUID(admin.sub),
            user_type="admin",
            action="template_updated",
            resource_type="notification_template",
            resource_id=event_type,
            details={
                "template_name": data.template_name,
            },
        ),
    )

    # Return the updated single template
    default_name = _EVENT_TEMPLATE_MAP[NotificationEventType(event_type)]
    return NotificationTemplateRead(
        event_type=event_type,
        template_name=data.template_name,
        description=_EVENT_DESCRIPTIONS.get(event_type, ""),
        priority=_EVENT_DEFAULT_PRIORITIES.get(
            event_type, NotificationPriority.medium.value
        ),
    )
