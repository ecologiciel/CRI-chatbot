"""ContactService — get or create contacts from WhatsApp messages.

Every inbound WhatsApp message triggers get_or_create: new numbers
become contacts automatically; known numbers get progressive enrichment
(name, language) from the WhatsApp profile and language detection.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.enums import ContactSource, Language, OptInStatus

logger = structlog.get_logger()


class ContactService:
    """Auto-create and update contacts from WhatsApp interactions."""

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
