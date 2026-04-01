"""NotificationService — proactive WhatsApp notifications for dossier changes.

Decides whether to send a notification based on the status-change matrix,
checks opt-in / deduplication, builds Meta template components, and fires
the message via WhatsAppSenderService.  Audit trail for every outcome.

All Redis keys are prefixed with ``{tenant.slug}:`` (multi-tenant invariant).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.enums import DossierStatut, Language, OptInStatus
from app.schemas.audit import AuditLogCreate
from app.services.audit.service import AuditService, get_audit_service
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────────

DEDUP_TTL_SECONDS: int = 86_400  # 24 hours

STATUT_LABELS: dict[str, dict[str, str]] = {
    "en_cours": {"fr": "En cours de traitement", "ar": "قيد المعالجة", "en": "Under processing"},
    "valide": {"fr": "Validé", "ar": "تمت الموافقة", "en": "Validated"},
    "rejete": {"fr": "Rejeté", "ar": "مرفوض", "en": "Rejected"},
    "en_attente": {"fr": "En attente", "ar": "في انتظار", "en": "Pending"},
    "complement": {"fr": "Complément demandé", "ar": "مطلوب تكملة", "en": "Supplement requested"},
    "incomplet": {"fr": "Incomplet", "ar": "غير مكتمل", "en": "Incomplete"},
}


# ── Enums & dataclasses ──────────────────────────────────────────────


class NotificationEventType(str, Enum):
    """Types of proactive notification events."""

    decision_finale = "decision_finale"
    complement_request = "complement_request"
    status_update = "status_update"
    dossier_incomplet = "dossier_incomplet"


class NotificationPriority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


@dataclass
class NotificationDecision:
    """Result of the should_notify decision matrix."""

    should_send: bool
    event_type: NotificationEventType | None = None
    priority: NotificationPriority = NotificationPriority.medium
    template_name: str | None = None
    reason: str | None = None


class DossierChangeEvent(BaseModel):
    """Event published by the import worker to the Redis queue."""

    dossier_id: str
    numero: str
    contact_id: str | None = None
    old_statut: str
    new_statut: str
    sync_log_id: str | None = None
    timestamp: str | None = None


# ── Template mapping ─────────────────────────────────────────────────

_EVENT_TEMPLATE_MAP: dict[NotificationEventType, str] = {
    NotificationEventType.decision_finale: "dossier_decision_finale",
    NotificationEventType.complement_request: "dossier_complement_request",
    NotificationEventType.status_update: "dossier_status_update",
    NotificationEventType.dossier_incomplet: "dossier_incomplet",
}


# ── Service ──────────────────────────────────────────────────────────


class NotificationService:
    """Proactive notification logic for dossier status changes.

    Responsibilities:
    - Decision matrix (should_notify)
    - Opt-in check
    - 24h deduplication via Redis
    - Template variable building
    - WhatsApp send with retry
    - Audit trail for every outcome
    """

    def __init__(
        self,
        sender: WhatsAppSenderService,
        audit: AuditService,
    ) -> None:
        self._sender = sender
        self._audit = audit
        self._logger = logger.bind(service="notification_service")

    # ── Decision matrix ──────────────────────────────────────────

    def should_notify(
        self,
        old_statut: str,
        new_statut: str,
    ) -> NotificationDecision:
        """Determine whether a status change warrants a notification.

        Pure logic — no I/O.

        Args:
            old_statut: Previous DossierStatut value.
            new_statut: New DossierStatut value.

        Returns:
            NotificationDecision with send flag, event type, and template.
        """
        if old_statut == new_statut:
            return NotificationDecision(
                should_send=False,
                reason="same_status",
            )

        # Terminal decisions — always high priority
        if new_statut in (DossierStatut.valide.value, DossierStatut.rejete.value):
            return NotificationDecision(
                should_send=True,
                event_type=NotificationEventType.decision_finale,
                priority=NotificationPriority.high,
                template_name=_EVENT_TEMPLATE_MAP[NotificationEventType.decision_finale],
            )

        # Complement request (explicit complement statut or en_attente→incomplet)
        if new_statut == DossierStatut.complement.value:
            return NotificationDecision(
                should_send=True,
                event_type=NotificationEventType.complement_request,
                priority=NotificationPriority.high,
                template_name=_EVENT_TEMPLATE_MAP[NotificationEventType.complement_request],
            )

        if (
            new_statut == DossierStatut.incomplet.value
            and old_statut == DossierStatut.en_attente.value
        ):
            return NotificationDecision(
                should_send=True,
                event_type=NotificationEventType.complement_request,
                priority=NotificationPriority.high,
                template_name=_EVENT_TEMPLATE_MAP[NotificationEventType.complement_request],
            )

        # Progress update (incomplet/en_attente → en_cours)
        if new_statut == DossierStatut.en_cours.value and old_statut in (
            DossierStatut.incomplet.value,
            DossierStatut.en_attente.value,
        ):
            return NotificationDecision(
                should_send=True,
                event_type=NotificationEventType.status_update,
                priority=NotificationPriority.medium,
                template_name=_EVENT_TEMPLATE_MAP[NotificationEventType.status_update],
            )

        # Generic incomplet from other states
        if new_statut == DossierStatut.incomplet.value:
            return NotificationDecision(
                should_send=True,
                event_type=NotificationEventType.dossier_incomplet,
                priority=NotificationPriority.low,
                template_name=_EVENT_TEMPLATE_MAP[NotificationEventType.dossier_incomplet],
            )

        # All other transitions — no notification
        return NotificationDecision(
            should_send=False,
            reason="no_matching_rule",
        )

    # ── Template helpers ─────────────────────────────────────────

    def get_template_name(self, event_type: NotificationEventType) -> str:
        """Return the Meta-approved template name for the event type."""
        return _EVENT_TEMPLATE_MAP[event_type]

    def build_template_components(
        self,
        contact_name: str,
        dossier_numero: str,
        event_type: NotificationEventType,
        language_code: str,
    ) -> list[dict[str, Any]]:
        """Build Meta Cloud API template components.

        Template body parameters:
        - {{1}} = contact name (or "Investisseur")
        - {{2}} = dossier numero
        - {{3}} = new status label (localised)
        - {{4}} = date (localised)

        Args:
            contact_name: Display name of the contact.
            dossier_numero: Dossier reference number.
            event_type: Notification event type (for status label).
            language_code: ISO language code (fr/ar/en).

        Returns:
            List of component dicts ready for send_template.
        """
        # Resolve status label from the event type
        status_label = self._status_label_for_event(event_type, language_code)

        # Date formatting
        now = datetime.now(UTC)
        if language_code == "ar":
            date_str = now.strftime("%Y/%m/%d")
        else:
            date_str = now.strftime("%d/%m/%Y")

        parameters = [
            {"type": "text", "text": contact_name or "Investisseur"},
            {"type": "text", "text": dossier_numero},
            {"type": "text", "text": status_label},
            {"type": "text", "text": date_str},
        ]

        return [{"type": "body", "parameters": parameters}]

    @staticmethod
    def _status_label_for_event(
        event_type: NotificationEventType,
        language_code: str,
    ) -> str:
        """Map event type back to a human-readable status label."""
        mapping: dict[NotificationEventType, str] = {
            NotificationEventType.decision_finale: "valide",  # overridden by caller context
            NotificationEventType.complement_request: "complement",
            NotificationEventType.status_update: "en_cours",
            NotificationEventType.dossier_incomplet: "incomplet",
        }
        statut_key = mapping.get(event_type, "en_cours")
        lang = language_code if language_code in ("fr", "ar", "en") else "fr"
        return STATUT_LABELS.get(statut_key, STATUT_LABELS["en_cours"])[lang]

    # ── Opt-in check ─────────────────────────────────────────────

    async def check_opt_in(
        self,
        contact_id: uuid.UUID,
        tenant: TenantContext,
    ) -> bool:
        """Check whether the contact has not opted out.

        ``pending`` is treated as opt-in (WhatsApp contacts who write first
        are implicitly opted in).

        Returns:
            True if the contact may receive notifications.
        """
        contact = await self._load_contact(contact_id, tenant)
        if contact is None:
            return False
        return contact.opt_in_status != OptInStatus.opted_out

    async def _load_contact(
        self,
        contact_id: uuid.UUID,
        tenant: TenantContext,
    ) -> Contact | None:
        """Load a contact by ID within the tenant's schema."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == contact_id),
            )
            return result.scalar_one_or_none()

    # ── Deduplication ────────────────────────────────────────────

    async def is_duplicate(
        self,
        contact_id: str,
        event_type: str,
        dossier_id: str,
        tenant: TenantContext,
    ) -> bool:
        """Check 24h deduplication via Redis SET NX.

        Key: ``{slug}:notif:dedup:{contact_id}:{event_type}:{dossier_id}``

        Returns:
            True if a notification was already sent (duplicate).
        """
        redis = get_redis()
        key = f"{tenant.slug}:notif:dedup:{contact_id}:{event_type}:{dossier_id}"
        was_set = await redis.set(key, "1", ex=DEDUP_TTL_SECONDS, nx=True)
        # was_set is True if the key was newly created, None if it already existed
        return was_set is None

    # ── Main orchestrator ────────────────────────────────────────

    async def send_notification(
        self,
        event: DossierChangeEvent,
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Process a single dossier-change event end-to-end.

        Flow: should_notify → load contact → check_opt_in → deduplicate
              → build template → send WhatsApp → audit trail.

        Args:
            event: Dossier change event from the Redis queue.
            tenant: Current tenant context.

        Returns:
            Dict with ``status`` key and optional details.
        """
        log = self._logger.bind(
            tenant=tenant.slug,
            dossier_id=event.dossier_id,
            numero=event.numero,
        )

        # 1. Decision matrix
        decision = self.should_notify(event.old_statut, event.new_statut)
        if not decision.should_send:
            log.debug("notification_skipped", reason=decision.reason)
            return {"status": "skipped", "reason": decision.reason}

        assert decision.event_type is not None
        assert decision.template_name is not None

        # 2. Contact check
        if not event.contact_id:
            log.debug("notification_skipped_no_contact")
            await self._audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_type="system",
                    action="notification_skipped",
                    resource_type="notification",
                    resource_id=event.dossier_id,
                    details={"reason": "no_contact_id"},
                ),
            )
            return {"status": "skipped", "reason": "no_contact_id"}

        contact_uuid = uuid.UUID(event.contact_id)
        contact = await self._load_contact(contact_uuid, tenant)
        if contact is None:
            log.warning("notification_skipped_contact_not_found", contact_id=event.contact_id)
            return {"status": "skipped", "reason": "contact_not_found"}

        # 3. Opt-in check
        if contact.opt_in_status == OptInStatus.opted_out:
            log.info("notification_skipped_optout", contact_id=event.contact_id)
            await self._audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_type="system",
                    action="notification_skipped",
                    resource_type="notification",
                    resource_id=event.dossier_id,
                    details={
                        "reason": "opted_out",
                        "contact_id": event.contact_id,
                    },
                ),
            )
            return {"status": "skipped", "reason": "opted_out"}

        # 4. Deduplication
        if await self.is_duplicate(
            event.contact_id,
            decision.event_type.value,
            event.dossier_id,
            tenant,
        ):
            log.info("notification_deduplicated", contact_id=event.contact_id)
            return {"status": "skipped", "reason": "deduplicated"}

        # 5. Build template
        language_code = contact.language.value if contact.language else "fr"
        contact_name = contact.name or "Investisseur"

        # For decision_finale, resolve the actual new status label
        components = self.build_template_components(
            contact_name=contact_name,
            dossier_numero=event.numero,
            event_type=decision.event_type,
            language_code=language_code,
        )

        # Override status label for decision_finale (valide vs rejete)
        if decision.event_type == NotificationEventType.decision_finale:
            lang = language_code if language_code in ("fr", "ar", "en") else "fr"
            actual_label = STATUT_LABELS.get(event.new_statut, STATUT_LABELS["valide"])[lang]
            components[0]["parameters"][2]["text"] = actual_label

        # 6. Send via WhatsApp
        if not contact.phone:
            log.warning("notification_skipped_no_phone", contact_id=event.contact_id)
            return {"status": "skipped", "reason": "no_phone"}

        try:
            wamid = await self._sender.send_template(
                tenant=tenant,
                to=contact.phone,
                template_name=decision.template_name,
                language_code=language_code,
                components=components,
            )
        except Exception as exc:
            log.error(
                "notification_send_failed",
                contact_id=event.contact_id,
                error=str(exc),
                exc_info=True,
            )
            await self._audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_type="system",
                    action="notification_failed",
                    resource_type="notification",
                    resource_id=event.dossier_id,
                    details={
                        "contact_id": event.contact_id,
                        "event_type": decision.event_type.value,
                        "error": str(exc),
                    },
                ),
            )
            return {"status": "failed", "error": str(exc)}

        # 7. Audit success
        log.info(
            "notification_sent",
            contact_id=event.contact_id,
            event_type=decision.event_type.value,
            wamid=wamid,
        )
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_type="system",
                action="notification_sent",
                resource_type="notification",
                resource_id=event.dossier_id,
                details={
                    "contact_id": event.contact_id,
                    "event_type": decision.event_type.value,
                    "template": decision.template_name,
                    "wamid": wamid,
                    "numero": event.numero,
                },
            ),
        )

        return {"status": "sent", "wamid": wamid, "event_type": decision.event_type.value}


# ── Singleton ────────────────────────────────────────────────────────

_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get or create the NotificationService singleton."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(
            sender=WhatsAppSenderService(),
            audit=get_audit_service(),
        )
    return _notification_service
