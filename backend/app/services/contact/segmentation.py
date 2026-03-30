"""SegmentationService — predefined contact segments and STOP command processing.

Segments are query-based (computed on-the-fly) rather than stored, so they
never go stale.  The STOP command handler implements CNDP-compliant opt-out
with audit logging.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import Select, func, select

from app.core.exceptions import ValidationError
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import ContactSource, OptInStatus
from app.schemas.audit import AuditLogCreate
from app.schemas.contacts_extended import SegmentInfo

logger = structlog.get_logger()

# Keywords that trigger CNDP opt-out (entire message must match).
STOP_KEYWORDS: frozenset[str] = frozenset(
    {
        "stop",
        "arreter",
        "arrêter",
        "desabonner",
        "désabonner",
        "unsubscribe",
    }
)


@dataclass(frozen=True)
class _SegmentDef:
    """Internal definition of a predefined segment."""

    key: str
    label_fr: str
    label_en: str
    description_fr: str
    filter_fn: Callable[[], Select[tuple[Contact]]]


def _build_segment_definitions() -> dict[str, _SegmentDef]:
    """Build the map of predefined segment definitions.

    Each segment is a named key → callable returning a filtered
    ``select(Contact)`` query.  The callable is evaluated at query time
    so that ``now`` is always fresh.
    """

    def _opted_in() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.opt_in_status == OptInStatus.opted_in)

    def _opted_out() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.opt_in_status == OptInStatus.opted_out)

    def _pending() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.opt_in_status == OptInStatus.pending)

    def _from_whatsapp() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.source == ContactSource.whatsapp)

    def _from_import() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.source == ContactSource.import_csv)

    def _from_manual() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.source == ContactSource.manual)

    def _has_cin() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.cin.isnot(None))

    def _no_cin() -> Select[tuple[Contact]]:
        return select(Contact).where(Contact.cin.is_(None))

    def _new_30d() -> Select[tuple[Contact]]:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        return select(Contact).where(Contact.created_at >= cutoff)

    def _inactive_90d() -> Select[tuple[Contact]]:
        """Contacts whose last message is older than 90 days or who have none."""
        cutoff = datetime.now(UTC) - timedelta(days=90)
        # Subquery: contacts who have at least one message after cutoff
        active_subq = (
            select(Conversation.contact_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.timestamp >= cutoff)
            .distinct()
            .correlate(None)
            .scalar_subquery()
        )
        return select(Contact).where(Contact.id.notin_(active_subq))

    defs: list[_SegmentDef] = [
        _SegmentDef(
            "opted_in",
            "Opt-in actif",
            "Opted in",
            "Contacts ayant accepté les communications",
            _opted_in,
        ),
        _SegmentDef(
            "opted_out",
            "Désinscrits",
            "Opted out",
            "Contacts ayant refusé les communications",
            _opted_out,
        ),
        _SegmentDef(
            "pending",
            "En attente",
            "Pending",
            "Contacts sans statut de consentement confirmé",
            _pending,
        ),
        _SegmentDef(
            "from_whatsapp",
            "Via WhatsApp",
            "From WhatsApp",
            "Contacts créés automatiquement depuis WhatsApp",
            _from_whatsapp,
        ),
        _SegmentDef(
            "from_import",
            "Importés",
            "Imported",
            "Contacts importés depuis fichier Excel/CSV",
            _from_import,
        ),
        _SegmentDef(
            "from_manual",
            "Création manuelle",
            "Manual",
            "Contacts créés manuellement dans le back-office",
            _from_manual,
        ),
        _SegmentDef(
            "has_cin", "CIN renseigné", "Has CIN", "Contacts dont le CIN est renseigné", _has_cin
        ),
        _SegmentDef("no_cin", "CIN manquant", "No CIN", "Contacts sans CIN", _no_cin),
        _SegmentDef(
            "new_30d",
            "Nouveaux (30j)",
            "New (30d)",
            "Contacts créés dans les 30 derniers jours",
            _new_30d,
        ),
        _SegmentDef(
            "inactive_90d",
            "Inactifs (90j)",
            "Inactive (90d)",
            "Contacts sans interaction depuis 90 jours",
            _inactive_90d,
        ),
    ]
    return {d.key: d for d in defs}


SEGMENTS = _build_segment_definitions()


class SegmentationService:
    """Contact segmentation and CNDP STOP-command processing."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="segmentation_service")

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    async def list_segments(self, tenant: TenantContext) -> list[SegmentInfo]:
        """Return all predefined segments with their current contact counts.

        Args:
            tenant: Tenant context for DB session.

        Returns:
            List of SegmentInfo with live counts.
        """
        results: list[SegmentInfo] = []
        async with tenant.db_session() as session:
            for seg_def in SEGMENTS.values():
                base_query = seg_def.filter_fn()
                count_query = select(func.count()).select_from(base_query.subquery())
                count = (await session.execute(count_query)).scalar_one()
                results.append(
                    SegmentInfo(
                        key=seg_def.key,
                        label_fr=seg_def.label_fr,
                        label_en=seg_def.label_en,
                        description_fr=seg_def.description_fr,
                        count=count,
                    ),
                )
        return results

    async def get_segment_contacts(
        self,
        tenant: TenantContext,
        segment_key: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Contact], int]:
        """Return contacts matching a named segment, with pagination.

        Args:
            tenant: Tenant context.
            segment_key: One of the predefined segment keys.
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            Tuple of (contacts list, total count).

        Raises:
            ValidationError: If segment_key is unknown.
        """
        seg_def = SEGMENTS.get(segment_key)
        if seg_def is None:
            valid = ", ".join(sorted(SEGMENTS.keys()))
            raise ValidationError(
                f"Unknown segment '{segment_key}'. Valid segments: {valid}",
            )

        base_query = seg_def.filter_fn()

        async with tenant.db_session() as session:
            # Count
            count_query = select(func.count()).select_from(base_query.subquery())
            total = (await session.execute(count_query)).scalar_one()

            # Paginated results
            offset = (page - 1) * page_size
            data_query = (
                base_query.order_by(Contact.created_at.desc()).offset(offset).limit(page_size)
            )
            contacts = (await session.execute(data_query)).scalars().all()

        return list(contacts), total

    # ------------------------------------------------------------------
    # STOP command (CNDP §9.9)
    # ------------------------------------------------------------------

    @staticmethod
    def is_stop_command(text: str) -> bool:
        """Check whether the entire message is a STOP opt-out keyword.

        Only exact matches (stripped, lowered) count — ``"STOP talking"``
        does **not** trigger opt-out.

        Args:
            text: Raw message text.

        Returns:
            True if the message is a STOP command.
        """
        return text.strip().lower() in STOP_KEYWORDS

    async def process_stop_command(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> bool:
        """Process a CNDP opt-out STOP command from WhatsApp.

        1. Find contact by phone.
        2. If not found or already opted_out → return False.
        3. Set opt_in_status to opted_out.
        4. Fire-and-forget audit log.
        5. Return True.

        Args:
            tenant: Tenant context.
            phone: E.164 phone number.

        Returns:
            True if the contact was opted out, False otherwise.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.phone == phone),
            )
            contact = result.scalar_one_or_none()

            if contact is None or contact.opt_in_status == OptInStatus.opted_out:
                return False

            previous = contact.opt_in_status.value
            contact.opt_in_status = OptInStatus.opted_out
            await session.flush()

        self._logger.info(
            "stop_command_processed",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
            previous_status=previous,
        )

        # Fire-and-forget CNDP audit entry
        try:
            from app.services.audit.service import get_audit_service

            await get_audit_service().log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_id=None,
                    user_type="system",
                    action="opt_in_change",
                    resource_type="contact",
                    resource_id=str(contact.id),
                    details={
                        "previous_status": previous,
                        "new_status": OptInStatus.opted_out.value,
                        "source": "user_stop",
                    },
                ),
            )
        except Exception:
            self._logger.error("stop_audit_log_failed", exc_info=True)

        return True


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_segmentation_service: SegmentationService | None = None


def get_segmentation_service() -> SegmentationService:
    """Get or create the SegmentationService singleton."""
    global _segmentation_service  # noqa: PLW0603
    if _segmentation_service is None:
        _segmentation_service = SegmentationService()
    return _segmentation_service
