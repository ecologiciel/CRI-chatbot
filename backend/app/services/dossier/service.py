"""Dossier consultation service — lookup, anti-BOLA checks, WhatsApp formatting.

Security invariant: WhatsApp users can ONLY access dossiers linked to their
OTP-verified phone number.  Every denied access attempt is audit-logged.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import CRIBaseException, ResourceNotFoundError
from app.core.metrics import BOLA_ATTEMPTS
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.dossier import Dossier
from app.models.enums import DossierStatut, Language
from app.schemas.audit import AuditLogCreate
from app.schemas.dossier import (
    DossierDetail,
    DossierFilters,
    DossierList,
    DossierRead,
    DossierStats,
)
from app.services.audit.service import AuditService, get_audit_service

logger = structlog.get_logger()

# ── Status label translations ───────────────────────────────────

STATUT_LABELS: dict[Language, dict[DossierStatut, str]] = {
    Language.fr: {
        DossierStatut.en_cours: "En cours de traitement",
        DossierStatut.valide: "Validé ✅",
        DossierStatut.rejete: "Rejeté ❌",
        DossierStatut.en_attente: "En attente de compléments ⏳",
        DossierStatut.complement: "Complément demandé 📎",
        DossierStatut.incomplet: "Dossier incomplet ⚠️",
    },
    Language.ar: {
        DossierStatut.en_cours: "قيد المعالجة",
        DossierStatut.valide: "✅ تمت الموافقة",
        DossierStatut.rejete: "❌ مرفوض",
        DossierStatut.en_attente: "⏳ في انتظار المستندات",
        DossierStatut.complement: "📎 مطلوب تكملة",
        DossierStatut.incomplet: "⚠️ ملف غير مكتمل",
    },
    Language.en: {
        DossierStatut.en_cours: "Under review",
        DossierStatut.valide: "Approved ✅",
        DossierStatut.rejete: "Rejected ❌",
        DossierStatut.en_attente: "Pending additional documents ⏳",
        DossierStatut.complement: "Supplement requested 📎",
        DossierStatut.incomplet: "Incomplete file ⚠️",
    },
}


# ── Exception ────────────────────────────────────────────────────


class UnauthorizedDossierAccess(CRIBaseException):
    """Tentative d'accès à un dossier non autorisé (anti-BOLA)."""

    def __init__(self, phone: str, dossier_id: str) -> None:
        super().__init__(
            message=f"Unauthorized access attempt to dossier {dossier_id}",
            details={"phone_last4": phone[-4:], "dossier_id": dossier_id},
        )


# ── Service ──────────────────────────────────────────────────────


class DossierService:
    """Dossier consultation with anti-BOLA protection and WhatsApp formatting."""

    def __init__(self, audit: AuditService) -> None:
        self._audit = audit
        self._logger = logger.bind(service="dossier_service")

    # ── Private helpers ──────────────────────────────────────────

    @staticmethod
    async def _get_contact_by_phone(
        session: AsyncSession,
        phone: str,
    ) -> Contact | None:
        """Look up a contact by phone number within an existing session."""
        result = await session.execute(
            select(Contact).where(Contact.phone == phone)
        )
        return result.scalar_one_or_none()

    # ── Public methods ───────────────────────────────────────────

    async def get_dossier_by_numero(
        self,
        tenant: TenantContext,
        numero: str,
    ) -> DossierDetail | None:
        """Look up a dossier by its unique numero.

        Returns None if not found (no exception).
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Dossier)
                .where(Dossier.numero == numero)
                .options(selectinload(Dossier.history))
            )
            dossier = result.scalar_one_or_none()

        if dossier is None:
            return None

        self._logger.debug(
            "dossier_found_by_numero",
            tenant=tenant.slug,
            numero=numero,
        )
        return DossierDetail.model_validate(dossier)

    async def get_dossiers_by_phone(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> list[DossierRead]:
        """Return all dossiers owned by the given phone (anti-BOLA safe).

        The query is intrinsically scoped to the OTP-verified phone's contact.
        Returns an empty list if the phone has no contact record.
        """
        async with tenant.db_session() as session:
            contact = await self._get_contact_by_phone(session, phone)
            if contact is None:
                self._logger.debug(
                    "dossier_list_no_contact",
                    tenant=tenant.slug,
                    phone_last4=phone[-4:],
                )
                return []

            result = await session.execute(
                select(Dossier)
                .where(Dossier.contact_id == contact.id)
                .order_by(Dossier.created_at.desc())
            )
            dossiers = list(result.scalars().all())

        self._logger.info(
            "dossier_list_by_phone",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
            count=len(dossiers),
        )

        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=None,
                user_type="whatsapp_user",
                action="dossier_list",
                resource_type="dossier",
                resource_id=None,
                details={
                    "phone_last4": phone[-4:],
                    "count": len(dossiers),
                },
            )
        )

        return [DossierRead.model_validate(d) for d in dossiers]

    async def get_dossier_with_bola_check(
        self,
        tenant: TenantContext,
        dossier_id: uuid.UUID,
        phone: str,
    ) -> DossierDetail:
        """Load a dossier and verify that the phone owns it (anti-BOLA).

        Raises:
            ResourceNotFoundError: Dossier does not exist.
            UnauthorizedDossierAccess: Phone does not own the dossier.
        """
        async with tenant.db_session() as session:
            # Load dossier with history
            result = await session.execute(
                select(Dossier)
                .where(Dossier.id == dossier_id)
                .options(selectinload(Dossier.history))
            )
            dossier = result.scalar_one_or_none()

            if dossier is None:
                raise ResourceNotFoundError(
                    message=f"Dossier not found: {dossier_id}",
                    details={"dossier_id": str(dossier_id)},
                )

            # Resolve contact from OTP-verified phone
            contact = await self._get_contact_by_phone(session, phone)

        # BOLA check: contact must exist AND own the dossier
        if contact is None or dossier.contact_id != contact.id:
            BOLA_ATTEMPTS.labels(tenant=tenant.slug).inc()
            self._logger.warning(
                "bola_violation",
                tenant=tenant.slug,
                dossier_id=str(dossier_id),
                phone_last4=phone[-4:],
            )
            await self._audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_id=None,
                    user_type="whatsapp_user",
                    action="access_denied",
                    resource_type="dossier",
                    resource_id=str(dossier_id),
                    details={
                        "phone_last4": phone[-4:],
                        "dossier_id": str(dossier_id),
                        "reason": "bola_violation",
                    },
                )
            )
            raise UnauthorizedDossierAccess(phone, str(dossier_id))

        # Access granted
        self._logger.info(
            "dossier_access_granted",
            tenant=tenant.slug,
            dossier_id=str(dossier_id),
            phone_last4=phone[-4:],
        )
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=None,
                user_type="whatsapp_user",
                action="access",
                resource_type="dossier",
                resource_id=str(dossier_id),
                details={
                    "phone_last4": phone[-4:],
                    "dossier_id": str(dossier_id),
                },
            )
        )

        return DossierDetail.model_validate(dossier)

    async def get_dossier_stats(
        self,
        tenant: TenantContext,
    ) -> DossierStats:
        """Return aggregated dossier KPIs for the tenant."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.en_cours)
                    .label("en_cours"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.valide)
                    .label("valide"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.rejete)
                    .label("rejete"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.en_attente)
                    .label("en_attente"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.complement)
                    .label("complement"),
                    func.count()
                    .filter(Dossier.statut == DossierStatut.incomplet)
                    .label("incomplet"),
                )
            )
            row = result.one()

        return DossierStats(
            total=row.total,
            en_cours=row.en_cours,
            valide=row.valide,
            rejete=row.rejete,
            en_attente=row.en_attente,
            complement=row.complement,
            incomplet=row.incomplet,
        )

    async def list_dossiers(
        self,
        tenant: TenantContext,
        *,
        filters: DossierFilters | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> DossierList:
        """Paginated dossier listing with dynamic filters (back-office only)."""
        async with tenant.db_session() as session:
            base = select(Dossier)

            if filters is not None:
                if filters.statut is not None:
                    base = base.where(Dossier.statut == filters.statut)
                if filters.type_projet is not None:
                    base = base.where(
                        Dossier.type_projet.ilike(f"%{filters.type_projet}%")
                    )
                if filters.date_depot_from is not None:
                    base = base.where(Dossier.date_depot >= filters.date_depot_from)
                if filters.date_depot_to is not None:
                    base = base.where(Dossier.date_depot <= filters.date_depot_to)
                if filters.search is not None:
                    pattern = f"%{filters.search}%"
                    base = base.where(
                        or_(
                            Dossier.numero.ilike(pattern),
                            Dossier.raison_sociale.ilike(pattern),
                        )
                    )

            # Total count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery())
            )
            total = count_result.scalar_one()

            # Paginated data
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(Dossier.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            items = list(data_result.scalars().all())

        return DossierList(
            items=[DossierRead.model_validate(d) for d in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    # ── WhatsApp formatting ──────────────────────────────────────

    def format_dossier_for_whatsapp(
        self,
        dossier: DossierDetail,
        language: Language = Language.fr,
    ) -> str:
        """Format dossier details for WhatsApp message.

        Security: NEVER includes montant_investissement, CIN, raw_data,
        or contact_id in the output.  Omits fields that are None.
        """
        lang = language if language in STATUT_LABELS else Language.fr
        statut_label = STATUT_LABELS[lang].get(
            dossier.statut,
            STATUT_LABELS[Language.fr][dossier.statut],
        )

        if lang == Language.ar:
            return self._format_ar(dossier, statut_label)
        if lang == Language.en:
            return self._format_en(dossier, statut_label)
        return self._format_fr(dossier, statut_label)

    @staticmethod
    def _format_fr(dossier: DossierDetail, statut_label: str) -> str:
        lines = [f"📋 *Dossier N° {dossier.numero}*"]
        lines.append(f"📊 Statut : {statut_label}")
        if dossier.date_derniere_maj is not None:
            lines.append(f"📅 Dernière mise à jour : {dossier.date_derniere_maj}")
        if dossier.raison_sociale is not None:
            lines.append(f"🏢 Raison sociale : {dossier.raison_sociale}")
        if dossier.type_projet is not None:
            lines.append(f"🏗️ Type de projet : {dossier.type_projet}")
        if dossier.region is not None:
            lines.append(f"📍 Région : {dossier.region}")
        if dossier.secteur is not None:
            lines.append(f"🏭 Secteur : {dossier.secteur}")
        if dossier.date_depot is not None:
            lines.append(f"📅 Date de dépôt : {dossier.date_depot}")
        if dossier.observations is not None:
            lines.append(f"📝 Observations : {dossier.observations}")
        return "\n".join(lines)

    @staticmethod
    def _format_ar(dossier: DossierDetail, statut_label: str) -> str:
        lines = [f"📋 *ملف رقم {dossier.numero}*"]
        lines.append(f"📊 الحالة : {statut_label}")
        if dossier.date_derniere_maj is not None:
            lines.append(f"📅 آخر تحديث : {dossier.date_derniere_maj}")
        if dossier.raison_sociale is not None:
            lines.append(f"🏢 الاسم التجاري : {dossier.raison_sociale}")
        if dossier.type_projet is not None:
            lines.append(f"🏗️ نوع المشروع : {dossier.type_projet}")
        if dossier.region is not None:
            lines.append(f"📍 الجهة : {dossier.region}")
        if dossier.secteur is not None:
            lines.append(f"🏭 القطاع : {dossier.secteur}")
        if dossier.date_depot is not None:
            lines.append(f"📅 تاريخ الإيداع : {dossier.date_depot}")
        if dossier.observations is not None:
            lines.append(f"📝 ملاحظات : {dossier.observations}")
        return "\n".join(lines)

    @staticmethod
    def _format_en(dossier: DossierDetail, statut_label: str) -> str:
        lines = [f"📋 *File N° {dossier.numero}*"]
        lines.append(f"📊 Status: {statut_label}")
        if dossier.date_derniere_maj is not None:
            lines.append(f"📅 Last updated: {dossier.date_derniere_maj}")
        if dossier.raison_sociale is not None:
            lines.append(f"🏢 Company: {dossier.raison_sociale}")
        if dossier.type_projet is not None:
            lines.append(f"🏗️ Project type: {dossier.type_projet}")
        if dossier.region is not None:
            lines.append(f"📍 Region: {dossier.region}")
        if dossier.secteur is not None:
            lines.append(f"🏭 Sector: {dossier.secteur}")
        if dossier.date_depot is not None:
            lines.append(f"📅 Filing date: {dossier.date_depot}")
        if dossier.observations is not None:
            lines.append(f"📝 Notes: {dossier.observations}")
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────

_dossier_service: DossierService | None = None


def get_dossier_service() -> DossierService:
    """Return the singleton DossierService instance."""
    global _dossier_service
    if _dossier_service is None:
        _dossier_service = DossierService(audit=get_audit_service())
    return _dossier_service
