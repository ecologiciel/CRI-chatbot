"""ContactService — CRUD for contacts, WhatsApp auto-create, search, and CRM.

Every inbound WhatsApp message triggers get_or_create: new numbers
become contacts automatically; known numbers get progressive enrichment
(name, language) from the WhatsApp profile and language detection.
The back-office CRUD methods (list, get_detail, create, update, delete)
are used by the contacts API.

Wave 17 additions: batch tag update, opt-in change with CNDP audit,
contact interaction history (conversations + campaigns).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.campaign import Campaign, CampaignRecipient
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import ContactSource, Language, OptInStatus
from app.schemas.audit import AuditLogCreate
from app.schemas.contact import ContactCreate, ContactUpdate

logger = structlog.get_logger()


class ContactService:
    """Contact management: WhatsApp auto-create + back-office CRUD."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="contact_service")

    async def get_or_create(
        self,
        tenant: TenantContext,
        phone: str,
        name: str | None = None,
        language: Language = Language.fr,
    ) -> Contact:
        """Get existing contact by phone or create a new one.

        Progressive enrichment: if the existing contact has no name and
        a name is provided (from WhatsApp profile), the name is updated.

        Args:
            tenant: Tenant context for DB session.
            phone: E.164 phone number (unique per tenant schema).
            name: Display name from WhatsApp profile.
            language: Default language for new contacts.

        Returns:
            Existing or newly created Contact ORM object.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.phone == phone),
            )
            contact = result.scalar_one_or_none()

            if contact is not None:
                # Progressive enrichment: update name if currently None
                if contact.name is None and name:
                    contact.name = name
                    self._logger.debug(
                        "contact_name_enriched",
                        tenant=tenant.slug,
                        phone_last4=phone[-4:] if len(phone) >= 4 else "***",
                    )
                return contact

            # Create new contact
            contact = Contact(
                phone=phone,
                name=name,
                language=language,
                source=ContactSource.whatsapp,
                opt_in_status=OptInStatus.pending,
                tags=[],
            )
            session.add(contact)
            await session.flush()

            self._logger.info(
                "contact_created",
                tenant=tenant.slug,
                contact_id=str(contact.id),
                phone_last4=phone[-4:] if len(phone) >= 4 else "***",
            )
            return contact

    # ── Back-office CRUD ──

    async def list_contacts(
        self,
        tenant: TenantContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        opt_in_status: OptInStatus | None = None,
        language: Language | None = None,
        tags: list[str] | None = None,
    ) -> tuple[list[Contact], int]:
        """List contacts with search, filters, and pagination.

        Returns:
            Tuple of (items, total_count).
        """
        async with tenant.db_session() as session:
            base = select(Contact)

            # Filters
            if search:
                pattern = f"%{search}%"
                base = base.where(
                    or_(
                        Contact.name.ilike(pattern),
                        Contact.phone.ilike(pattern),
                        Contact.cin.ilike(pattern),
                    )
                )
            if opt_in_status is not None:
                base = base.where(Contact.opt_in_status == opt_in_status)
            if language is not None:
                base = base.where(Contact.language == language)
            if tags:
                for tag in tags:
                    base = base.where(Contact.tags.contains([tag]))

            # Count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # Paginated data
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(Contact.created_at.desc()).offset(offset).limit(page_size),
            )
            items = list(data_result.scalars().all())

        return items, total

    async def get_contact_detail(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
    ) -> tuple[Contact, int, str | None]:
        """Get contact with conversation count and last interaction.

        Returns:
            Tuple of (contact, conversation_count, last_interaction_iso).

        Raises:
            ResourceNotFoundError: If contact does not exist.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact)
                .where(Contact.id == contact_id)
                .options(selectinload(Contact.conversations)),
            )
            contact = result.scalar_one_or_none()

            if contact is None:
                raise ResourceNotFoundError(
                    f"Contact not found: {contact_id}",
                    details={"contact_id": str(contact_id)},
                )

            conversation_count = len(contact.conversations)

            # Find the most recent message across all conversations
            last_interaction = None
            if conversation_count > 0:
                conv_ids = [c.id for c in contact.conversations]
                msg_result = await session.execute(
                    select(Message.timestamp)
                    .where(Message.conversation_id.in_(conv_ids))
                    .order_by(Message.timestamp.desc())
                    .limit(1),
                )
                last_msg_ts = msg_result.scalar_one_or_none()
                if last_msg_ts is not None:
                    last_interaction = last_msg_ts.isoformat()

        return contact, conversation_count, last_interaction

    async def create_contact(
        self,
        tenant: TenantContext,
        data: ContactCreate,
    ) -> Contact:
        """Create a new contact manually from the back-office.

        Raises:
            DuplicateResourceError: If phone already exists in tenant.
        """
        async with tenant.db_session() as session:
            # Check phone uniqueness
            existing = await session.execute(
                select(Contact.id).where(Contact.phone == data.phone),
            )
            if existing.scalar_one_or_none() is not None:
                raise DuplicateResourceError(
                    f"Contact with phone {data.phone} already exists",
                    details={"phone": data.phone},
                )

            contact = Contact(
                phone=data.phone,
                name=data.name,
                language=data.language,
                cin=data.cin,
                tags=data.tags,
                source=data.source,
                opt_in_status=OptInStatus.pending,
            )
            session.add(contact)
            await session.flush()
            await session.refresh(contact)

            self._logger.info(
                "contact_created_manual",
                tenant=tenant.slug,
                contact_id=str(contact.id),
                phone_last4=data.phone[-4:] if len(data.phone) >= 4 else "***",
            )
            return contact

    async def update_contact(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
        data: ContactUpdate,
    ) -> Contact:
        """Update a contact's fields (non-None fields only).

        Raises:
            ResourceNotFoundError: If contact does not exist.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == contact_id),
            )
            contact = result.scalar_one_or_none()
            if contact is None:
                raise ResourceNotFoundError(
                    f"Contact not found: {contact_id}",
                    details={"contact_id": str(contact_id)},
                )

            # Apply non-None fields
            if data.name is not None:
                contact.name = data.name
            if data.language is not None:
                contact.language = data.language
            if data.cin is not None:
                contact.cin = data.cin
            if data.opt_in_status is not None:
                contact.opt_in_status = data.opt_in_status
            if data.tags is not None:
                contact.tags = data.tags
            if data.source is not None:
                contact.source = data.source

            await session.flush()
            await session.refresh(contact)

            self._logger.info(
                "contact_updated",
                tenant=tenant.slug,
                contact_id=str(contact_id),
            )
            return contact

    async def delete_contact(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
    ) -> None:
        """Delete a contact and cascade to conversations/messages.

        Raises:
            ResourceNotFoundError: If contact does not exist.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == contact_id),
            )
            contact = result.scalar_one_or_none()
            if contact is None:
                raise ResourceNotFoundError(
                    f"Contact not found: {contact_id}",
                    details={"contact_id": str(contact_id)},
                )

            await session.delete(contact)
            self._logger.info(
                "contact_deleted",
                tenant=tenant.slug,
                contact_id=str(contact_id),
            )

    async def count_contacts(
        self,
        tenant: TenantContext,
    ) -> int:
        """Count total contacts for a tenant."""
        async with tenant.db_session() as session:
            result = await session.execute(
                select(func.count(Contact.id)),
            )
            return result.scalar_one()

    # ── CRM enrichment (Wave 17) ──

    async def batch_update_tags(
        self,
        tenant: TenantContext,
        contact_ids: list[uuid.UUID],
        *,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
    ) -> int:
        """Add and/or remove tags from multiple contacts atomically.

        Loads current tags, computes the new tag set in Python
        (set union for add, set difference for remove), and writes back.
        Only contacts whose tags actually change are counted.

        Args:
            tenant: Tenant context for DB session.
            contact_ids: Contact UUIDs (max 500).
            add_tags: Tags to add to each contact.
            remove_tags: Tags to remove from each contact.

        Returns:
            Number of contacts whose tags were modified.
        """
        add_set = set(add_tags) if add_tags else set()
        remove_set = set(remove_tags) if remove_tags else set()
        updated = 0

        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id.in_(contact_ids)),
            )
            contacts = result.scalars().all()

            for contact in contacts:
                existing = set(contact.tags or [])
                new_tags = (existing | add_set) - remove_set
                if new_tags != existing:
                    # Assign a new list so SQLAlchemy detects the change
                    contact.tags = sorted(new_tags)
                    updated += 1

        self._logger.info(
            "tags_batch_updated",
            tenant=tenant.slug,
            requested=len(contact_ids),
            found=len(contacts),
            updated=updated,
        )
        return updated

    async def change_opt_in_status(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
        *,
        new_status: OptInStatus,
        reason: str,
        admin_id: uuid.UUID | None = None,
    ) -> tuple[Contact, str]:
        """Change a contact's opt-in status with CNDP-compliant audit logging.

        Args:
            tenant: Tenant context.
            contact_id: Target contact UUID.
            new_status: Desired OptInStatus.
            reason: Human-readable reason for the change.
            admin_id: Admin who initiated the change (None for system).

        Returns:
            Tuple of (updated contact, previous status value string).

        Raises:
            ResourceNotFoundError: If the contact does not exist.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == contact_id),
            )
            contact = result.scalar_one_or_none()
            if contact is None:
                raise ResourceNotFoundError(
                    f"Contact not found: {contact_id}",
                    details={"contact_id": str(contact_id)},
                )

            previous = contact.opt_in_status.value
            if contact.opt_in_status == new_status:
                return contact, previous

            contact.opt_in_status = new_status
            await session.flush()

        self._logger.info(
            "opt_in_status_changed",
            tenant=tenant.slug,
            contact_id=str(contact_id),
            previous=previous,
            new=new_status.value,
        )

        # Fire-and-forget CNDP audit entry
        try:
            from app.services.audit.service import get_audit_service

            await get_audit_service().log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_id=admin_id,
                    user_type="admin" if admin_id else "system",
                    action="opt_in_change",
                    resource_type="contact",
                    resource_id=str(contact_id),
                    details={
                        "previous_status": previous,
                        "new_status": new_status.value,
                        "reason": reason,
                    },
                ),
            )
        except Exception:
            self._logger.error("opt_in_audit_log_failed", exc_info=True)

        return contact, previous

    async def get_contact_history(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
    ) -> dict:
        """Get full interaction history: conversations with message counts and campaigns.

        Args:
            tenant: Tenant context.
            contact_id: Target contact UUID.

        Returns:
            Dict with conversations, campaigns, total_conversations, total_campaigns.

        Raises:
            ResourceNotFoundError: If the contact does not exist.
        """
        async with tenant.db_session() as session:
            # Verify contact exists
            exists = await session.execute(
                select(Contact.id).where(Contact.id == contact_id),
            )
            if exists.scalar_one_or_none() is None:
                raise ResourceNotFoundError(
                    f"Contact not found: {contact_id}",
                    details={"contact_id": str(contact_id)},
                )

            # Conversations with message count and last message timestamp
            conv_result = await session.execute(
                select(
                    Conversation.id,
                    Conversation.status,
                    Conversation.agent_type,
                    Conversation.started_at,
                    Conversation.ended_at,
                    func.count(Message.id).label("message_count"),
                    func.max(Message.timestamp).label("last_message_at"),
                )
                .outerjoin(Message, Message.conversation_id == Conversation.id)
                .where(Conversation.contact_id == contact_id)
                .group_by(Conversation.id)
                .order_by(Conversation.started_at.desc()),
            )
            conversations = [
                {
                    "id": row.id,
                    "status": row.status,
                    "agent_type": row.agent_type,
                    "message_count": row.message_count,
                    "started_at": row.started_at,
                    "ended_at": row.ended_at,
                    "last_message_at": row.last_message_at,
                }
                for row in conv_result.all()
            ]

            # Campaign participations
            camp_result = await session.execute(
                select(
                    CampaignRecipient.campaign_id,
                    Campaign.name.label("campaign_name"),
                    CampaignRecipient.status,
                    CampaignRecipient.sent_at,
                    CampaignRecipient.delivered_at,
                    CampaignRecipient.read_at,
                )
                .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
                .where(CampaignRecipient.contact_id == contact_id)
                .order_by(CampaignRecipient.created_at.desc()),
            )
            campaigns = [
                {
                    "campaign_id": row.campaign_id,
                    "campaign_name": row.campaign_name,
                    "status": row.status,
                    "sent_at": row.sent_at,
                    "delivered_at": row.delivered_at,
                    "read_at": row.read_at,
                }
                for row in camp_result.all()
            ]

        return {
            "contact_id": contact_id,
            "conversations": conversations,
            "campaigns": campaigns,
            "total_conversations": len(conversations),
            "total_campaigns": len(campaigns),
        }

    # ── WhatsApp language detection ──

    async def update_language(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
        language: Language,
    ) -> None:
        """Update a contact's preferred language.

        Called after LangGraph detects the user's language from their message.

        Args:
            tenant: Tenant context for DB session.
            contact_id: UUID of the contact.
            language: Detected language enum.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.id == contact_id),
            )
            contact = result.scalar_one_or_none()
            if contact is not None and contact.language != language:
                contact.language = language
                self._logger.debug(
                    "contact_language_updated",
                    tenant=tenant.slug,
                    contact_id=str(contact_id),
                    language=language.value,
                )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_contact_service: ContactService | None = None


def get_contact_service() -> ContactService:
    """Get or create the ContactService singleton."""
    global _contact_service  # noqa: PLW0603
    if _contact_service is None:
        _contact_service = ContactService()
    return _contact_service
