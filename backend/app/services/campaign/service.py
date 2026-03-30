"""Campaign service — CRUD, audience targeting, quota, and lifecycle.

Manages the full campaign lifecycle: draft → scheduled → sending → completed.
Delegates actual message delivery to the ``send_campaign_task`` ARQ worker.

The annual quota (100 000 msg/tenant, CPS R13) is shared with regular
WhatsApp messaging via the same Redis counter managed by
:class:`WhatsAppSessionManager`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import cast, func, insert, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql.expression import Select
from sqlalchemy.types import Text as SAText

from app.core.exceptions import (
    ResourceNotFoundError,
    ValidationError,
    WhatsAppQuotaExhaustedError,
)
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.models.campaign import Campaign, CampaignRecipient
from app.models.contact import Contact
from app.models.enums import CampaignStatus, OptInStatus, RecipientStatus
from app.schemas.audit import AuditLogCreate
from app.schemas.campaign import AudiencePreview, CampaignCreate, CampaignStats, CampaignUpdate
from app.services.audit.service import AuditService, get_audit_service
from app.services.whatsapp.sender import WhatsAppSenderService
from app.services.whatsapp.session import WhatsAppSessionManager

logger = structlog.get_logger()

# ── Constants ──

QUOTA_WARNING_THRESHOLD = 0.80
QUOTA_CRITICAL_THRESHOLD = 0.95
DEFAULT_NAME_FALLBACK = "Investisseur"


class CampaignService:
    """Service for managing WhatsApp mass-messaging campaigns.

    Handles CRUD, audience resolution, quota checking, and campaign
    lifecycle management.  The actual message sending is delegated to
    the ``send_campaign_task`` ARQ worker.

    Args:
        sender: WhatsAppSenderService for template message delivery.
        audit: AuditService for audit trail logging.
        session_mgr: WhatsAppSessionManager for quota operations.
    """

    def __init__(
        self,
        sender: WhatsAppSenderService,
        audit: AuditService,
        session_mgr: WhatsAppSessionManager,
    ) -> None:
        self._sender = sender
        self._audit = audit
        self._session_mgr = session_mgr
        self._logger = logger.bind(service="campaign_service")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_campaign(
        self,
        tenant: TenantContext,
        data: CampaignCreate,
        admin_id: uuid.UUID,
    ) -> Campaign:
        """Create a new campaign in *draft* status.

        Computes the audience count from the provided filter (excluding
        contacts that are not opted-in).

        Args:
            tenant: Current tenant context.
            data: Campaign creation payload.
            admin_id: ID of the admin creating the campaign.

        Returns:
            The persisted Campaign ORM instance.
        """
        audience_count = await self._count_audience(tenant, data.audience_filter)

        async with tenant.db_session() as session:
            campaign = Campaign(
                name=data.name,
                description=data.description,
                template_id=data.template_id,
                template_name=data.template_name,
                template_language=data.template_language,
                audience_filter=data.audience_filter,
                audience_count=audience_count,
                variable_mapping=data.variable_mapping,
                status=CampaignStatus.draft,
                stats={"sent": 0, "delivered": 0, "read": 0, "failed": 0, "total": 0},
                created_by=admin_id,
            )
            session.add(campaign)
            await session.flush()

            self._logger.info(
                "campaign_created",
                tenant=tenant.slug,
                campaign_id=str(campaign.id),
                audience_count=audience_count,
            )

        await self._audit_log(tenant, admin_id, "create", campaign)
        return campaign

    async def update_campaign(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
        data: CampaignUpdate,
        admin_id: uuid.UUID,
    ) -> Campaign:
        """Update a campaign that is still in *draft* status.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign to update.
            data: Partial update payload.
            admin_id: ID of the admin performing the update.

        Returns:
            The updated Campaign ORM instance.

        Raises:
            ResourceNotFoundError: Campaign does not exist.
            ValidationError: Campaign is not in draft status.
        """
        async with tenant.db_session() as session:
            campaign = await self._load_campaign(session, campaign_id)

            if campaign.status != CampaignStatus.draft:
                raise ValidationError(
                    "Only draft campaigns can be edited",
                    details={"current_status": campaign.status.value},
                )

            update_fields = data.model_dump(exclude_unset=True)
            for field, value in update_fields.items():
                setattr(campaign, field, value)

            if "audience_filter" in update_fields:
                campaign.audience_count = await self._count_audience(
                    tenant,
                    campaign.audience_filter,
                )

            await session.flush()

        await self._audit_log(tenant, admin_id, "update", campaign)
        return campaign

    async def get_campaign(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
    ) -> Campaign:
        """Fetch a single campaign by ID.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.

        Returns:
            Campaign ORM instance.

        Raises:
            ResourceNotFoundError: Campaign does not exist.
        """
        async with tenant.db_session() as session:
            return await self._load_campaign(session, campaign_id)

    async def list_campaigns(
        self,
        tenant: TenantContext,
        page: int = 1,
        page_size: int = 20,
        status: CampaignStatus | None = None,
    ) -> tuple[list[Campaign], int]:
        """List campaigns with optional status filter, newest first.

        Args:
            tenant: Current tenant context.
            page: 1-based page number.
            page_size: Items per page.
            status: Optional status filter.

        Returns:
            Tuple of (campaign list, total count).
        """
        async with tenant.db_session() as session:
            base = select(Campaign)
            if status is not None:
                base = base.where(Campaign.status == status)

            total_q = select(func.count()).select_from(base.subquery())
            total = (await session.execute(total_q)).scalar_one()

            items_q = (
                base.order_by(Campaign.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = list((await session.execute(items_q)).scalars().all())

        return items, total

    # ------------------------------------------------------------------
    # Audience
    # ------------------------------------------------------------------

    async def preview_audience(
        self,
        tenant: TenantContext,
        audience_filter: dict,
    ) -> AudiencePreview:
        """Preview contacts matching an audience filter.

        Returns the total count and up to 5 sample contacts.
        Contacts not in ``opted_in`` status are always excluded.

        Args:
            tenant: Current tenant context.
            audience_filter: Targeting criteria dict.

        Returns:
            AudiencePreview with count and sample.
        """
        base_q = self._build_audience_query(audience_filter)

        async with tenant.db_session() as session:
            count_q = select(func.count()).select_from(base_q.subquery())
            count = (await session.execute(count_q)).scalar_one()

            sample_q = base_q.limit(5)
            rows = (await session.execute(sample_q)).scalars().all()

        sample = [
            {
                "id": str(c.id),
                "phone": f"***{c.phone[-4:]}",
                "name": c.name,
                "language": c.language.value,
                "tags": c.tags,
            }
            for c in rows
        ]
        return AudiencePreview(count=count, sample=sample)

    # ------------------------------------------------------------------
    # Quota
    # ------------------------------------------------------------------

    async def check_quota(
        self,
        tenant: TenantContext,
        count: int,
    ) -> dict[str, Any]:
        """Check whether the tenant can send *count* additional messages.

        Delegates to :class:`WhatsAppSessionManager` for the authoritative
        quota reading (shared Redis counter).

        Args:
            tenant: Current tenant context.
            count: Number of messages to send.

        Returns:
            Dict with ``allowed``, ``used``, ``limit``, ``remaining``,
            ``percentage`` keys.
        """
        quota_info = await self._session_mgr.check_quota(tenant)

        percentage = round(quota_info.annual_count / max(quota_info.annual_limit, 1) * 100, 1)

        if percentage >= QUOTA_CRITICAL_THRESHOLD * 100:
            self._logger.error(
                "quota_critical",
                tenant=tenant.slug,
                used=quota_info.annual_count,
                limit=quota_info.annual_limit,
            )
        elif percentage >= QUOTA_WARNING_THRESHOLD * 100:
            self._logger.warning(
                "quota_warning",
                tenant=tenant.slug,
                used=quota_info.annual_count,
                limit=quota_info.annual_limit,
            )

        return {
            "allowed": count <= quota_info.remaining,
            "used": quota_info.annual_count,
            "limit": quota_info.annual_limit,
            "remaining": quota_info.remaining,
            "percentage": percentage,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def launch_campaign(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
        admin_id: uuid.UUID,
    ) -> Campaign:
        """Launch a campaign: verify quota, materialise recipients, enqueue worker.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.
            admin_id: ID of the admin triggering the launch.

        Returns:
            The updated Campaign ORM instance.

        Raises:
            ResourceNotFoundError: Campaign does not exist.
            ValidationError: Campaign not in launchable status.
            WhatsAppQuotaExhaustedError: Annual quota insufficient.
        """
        async with tenant.db_session() as session:
            campaign = await self._load_campaign(session, campaign_id)

            if campaign.status not in (CampaignStatus.draft, CampaignStatus.scheduled):
                raise ValidationError(
                    "Campaign must be in draft or scheduled status to launch",
                    details={"current_status": campaign.status.value},
                )

            # Quota check
            quota = await self.check_quota(tenant, campaign.audience_count)
            if not quota["allowed"]:
                raise WhatsAppQuotaExhaustedError(
                    f"Insufficient quota: need {campaign.audience_count}, "
                    f"remaining {quota['remaining']}",
                )

            # Materialise recipients from audience filter
            base_q = self._build_audience_query(campaign.audience_filter)
            contacts = (await session.execute(base_q)).scalars().all()

            if contacts:
                recipient_rows = [
                    {
                        "id": uuid.uuid4(),
                        "campaign_id": campaign.id,
                        "contact_id": c.id,
                        "status": RecipientStatus.pending,
                        "created_at": datetime.now(UTC),
                    }
                    for c in contacts
                ]
                await session.execute(insert(CampaignRecipient), recipient_rows)

            actual_count = len(contacts)
            campaign.audience_count = actual_count
            campaign.status = CampaignStatus.sending
            campaign.started_at = datetime.now(UTC)
            campaign.stats = {
                "sent": 0,
                "delivered": 0,
                "read": 0,
                "failed": 0,
                "total": actual_count,
            }
            await session.flush()

        # Enqueue ARQ worker
        redis = get_redis()
        await redis.enqueue_job(
            "send_campaign_task",
            tenant.slug,
            str(campaign_id),
        )

        self._logger.info(
            "campaign_launched",
            tenant=tenant.slug,
            campaign_id=str(campaign_id),
            recipient_count=actual_count,
        )

        await self._audit_log(tenant, admin_id, "launch", campaign)
        return campaign

    async def pause_campaign(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
        admin_id: uuid.UUID,
    ) -> Campaign:
        """Pause a campaign that is currently sending.

        Sets a Redis flag checked by the send worker at each batch.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.
            admin_id: ID of the admin pausing the campaign.

        Returns:
            The updated Campaign ORM instance.

        Raises:
            ValidationError: Campaign is not in sending status.
        """
        async with tenant.db_session() as session:
            campaign = await self._load_campaign(session, campaign_id)

            if campaign.status != CampaignStatus.sending:
                raise ValidationError(
                    "Only sending campaigns can be paused",
                    details={"current_status": campaign.status.value},
                )

            campaign.status = CampaignStatus.paused
            await session.flush()

        redis = get_redis()
        await redis.set(
            f"{tenant.redis_prefix}:campaign:{campaign_id}:paused",
            "1",
            ex=86400,  # 24h TTL safety net
        )

        self._logger.info("campaign_paused", tenant=tenant.slug, campaign_id=str(campaign_id))
        await self._audit_log(tenant, admin_id, "pause", campaign)
        return campaign

    async def resume_campaign(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
        admin_id: uuid.UUID,
    ) -> Campaign:
        """Resume a paused campaign.

        Clears the Redis pause flag and re-enqueues the send worker
        which will pick up from the remaining ``pending`` recipients.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.
            admin_id: ID of the admin resuming the campaign.

        Returns:
            The updated Campaign ORM instance.

        Raises:
            ValidationError: Campaign is not in paused status.
        """
        async with tenant.db_session() as session:
            campaign = await self._load_campaign(session, campaign_id)

            if campaign.status != CampaignStatus.paused:
                raise ValidationError(
                    "Only paused campaigns can be resumed",
                    details={"current_status": campaign.status.value},
                )

            campaign.status = CampaignStatus.sending
            await session.flush()

        redis = get_redis()
        await redis.delete(f"{tenant.redis_prefix}:campaign:{campaign_id}:paused")

        # Re-enqueue worker — it will resume from pending recipients
        await redis.enqueue_job(
            "send_campaign_task",
            tenant.slug,
            str(campaign_id),
        )

        self._logger.info("campaign_resumed", tenant=tenant.slug, campaign_id=str(campaign_id))
        await self._audit_log(tenant, admin_id, "resume", campaign)
        return campaign

    # ------------------------------------------------------------------
    # Stats & recipients
    # ------------------------------------------------------------------

    async def get_campaign_stats(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
    ) -> CampaignStats:
        """Get real-time delivery statistics for a campaign.

        Reads from the campaign's ``stats`` JSONB column (updated
        atomically by the send worker).

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.

        Returns:
            CampaignStats with counts and delivery/read rates.
        """
        campaign = await self.get_campaign(tenant, campaign_id)
        stats = campaign.stats or {}

        total = stats.get("total", 0)
        sent = stats.get("sent", 0)
        delivered = stats.get("delivered", 0)
        read = stats.get("read", 0)
        failed = stats.get("failed", 0)
        pending = max(0, total - sent - failed)

        delivery_rate = round(delivered / sent * 100, 1) if sent > 0 else None
        read_rate = round(read / delivered * 100, 1) if delivered > 0 else None

        return CampaignStats(
            total=total,
            sent=sent,
            delivered=delivered,
            read=read,
            failed=failed,
            pending=pending,
            delivery_rate=delivery_rate,
            read_rate=read_rate,
        )

    async def get_recipients(
        self,
        tenant: TenantContext,
        campaign_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status: RecipientStatus | None = None,
    ) -> tuple[list[CampaignRecipient], int]:
        """List recipients of a campaign with optional status filter.

        Args:
            tenant: Current tenant context.
            campaign_id: UUID of the campaign.
            page: 1-based page number.
            page_size: Items per page.
            status: Optional recipient status filter.

        Returns:
            Tuple of (recipients list, total count).
        """
        async with tenant.db_session() as session:
            base = select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign_id,
            )
            if status is not None:
                base = base.where(CampaignRecipient.status == status)

            total_q = select(func.count()).select_from(base.subquery())
            total = (await session.execute(total_q)).scalar_one()

            items_q = (
                base.order_by(CampaignRecipient.created_at)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = list((await session.execute(items_q)).scalars().all())

        return items, total

    # ------------------------------------------------------------------
    # Variable resolution
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_variables(
        variable_mapping: dict[str, str],
        contact: Contact,
    ) -> list[dict[str, Any]]:
        """Resolve template variables for a specific contact.

        Supported mappings:
        - ``"contact.name"``  → contact name (fallback: ``"Investisseur"``)
        - ``"contact.phone"`` → contact phone (E.164)
        - ``"contact.language"`` → contact language code
        - ``"custom:<text>"`` → literal text

        Args:
            variable_mapping: Position-to-field mapping, e.g.
                ``{"1": "contact.name", "2": "custom:Bienvenue"}``.
            contact: The Contact ORM instance.

        Returns:
            WhatsApp template components list for ``send_template``.
            Returns ``[]`` if no variables are mapped.
        """
        if not variable_mapping:
            return []

        field_resolvers: dict[str, str] = {
            "contact.name": contact.name or DEFAULT_NAME_FALLBACK,
            "contact.phone": contact.phone,
            "contact.language": contact.language.value if contact.language else "fr",
        }

        parameters: list[dict[str, str]] = []
        for position in sorted(variable_mapping.keys(), key=lambda k: int(k)):
            field_path = variable_mapping[position]

            if field_path.startswith("custom:"):
                value = field_path[len("custom:") :]
            else:
                value = field_resolvers.get(field_path, "")

            parameters.append({"type": "text", "text": str(value)})

        return [{"type": "body", "parameters": parameters}]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_audience_query(audience_filter: dict) -> Select:
        """Build a SQLAlchemy SELECT for contacts matching *audience_filter*.

        Filters:
        - ``tags`` (list[str]): contacts with **any** of these tags
          (PostgreSQL ``?|`` operator on JSONB with GIN index).
        - ``language`` (str): exact language match.
        - ``exclude_tags`` (list[str]): exclude contacts with any of these tags.

        Opt-in exclusion is **always** applied: only ``opted_in`` contacts
        are included.
        """
        stmt: Select = select(Contact).where(
            Contact.opt_in_status == OptInStatus.opted_in,
        )

        tags = audience_filter.get("tags")
        if tags:
            stmt = stmt.where(
                Contact.tags.op("?|")(cast(tags, ARRAY(SAText))),
            )

        language = audience_filter.get("language")
        if language:
            stmt = stmt.where(Contact.language == language)

        exclude_tags = audience_filter.get("exclude_tags")
        if exclude_tags:
            # Exclude contacts with any of the excluded tags
            stmt = stmt.where(
                ~Contact.tags.op("?|")(cast(exclude_tags, ARRAY(SAText))),
            )

        return stmt

    async def _count_audience(
        self,
        tenant: TenantContext,
        audience_filter: dict,
    ) -> int:
        """Count contacts matching the audience filter."""
        base_q = self._build_audience_query(audience_filter)
        count_q = select(func.count()).select_from(base_q.subquery())

        async with tenant.db_session() as session:
            return (await session.execute(count_q)).scalar_one()

    @staticmethod
    async def _load_campaign(session: Any, campaign_id: uuid.UUID) -> Campaign:
        """Load a campaign by ID or raise ResourceNotFoundError."""
        result = await session.execute(
            select(Campaign).where(Campaign.id == campaign_id),
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise ResourceNotFoundError(
                f"Campaign {campaign_id} not found",
                details={"campaign_id": str(campaign_id)},
            )
        return campaign

    async def _audit_log(
        self,
        tenant: TenantContext,
        admin_id: uuid.UUID,
        action: str,
        campaign: Campaign,
    ) -> None:
        """Fire-and-forget audit log entry for a campaign action."""
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action=action,
                resource_type="campaign",
                resource_id=str(campaign.id),
                details={"name": campaign.name},
            ),
        )


# ── Singleton factory ──

_campaign_service: CampaignService | None = None


def get_campaign_service() -> CampaignService:
    """Get or create the CampaignService singleton."""
    global _campaign_service  # noqa: PLW0603
    if _campaign_service is None:
        _campaign_service = CampaignService(
            sender=WhatsAppSenderService(),
            audit=get_audit_service(),
            session_mgr=WhatsAppSessionManager(),
        )
    return _campaign_service
