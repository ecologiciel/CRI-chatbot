"""ContactService — CRUD for contacts, WhatsApp auto-create, and search.

Every inbound WhatsApp message triggers get_or_create: new numbers
become contacts automatically; known numbers get progressive enrichment
(name, language) from the WhatsApp profile and language detection.
The back-office CRUD methods (list, get_detail, create, update, delete)
are used by the contacts API.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import ContactSource, Language, OptInStatus
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
                base.order_by(Contact.created_at.desc())
                .offset(offset)
                .limit(page_size),
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
