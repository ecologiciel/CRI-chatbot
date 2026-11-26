"""Persist one authenticated WhatsApp message in an encrypted inbox.

This service is staged only: the webhook and worker do not call it yet.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_session_factory
from app.core.exceptions import TenantInactiveError
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import protect_ingestion
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.schemas.whatsapp import ContactInfo, IncomingMessage
from app.services.crypto.versioned_envelope import VersionedEnvelopeService

PURPOSE = "wa_inbox"


async def persist_incoming_message(
    tenant: TenantContext,
    phone_number_id: str,
    message: IncomingMessage,
    contacts: list[ContactInfo] | None,
    *,
    cipher: VersionedEnvelopeService,
) -> bool:
    """Commit an event or report an already stored event for this tenant.

    Callers must authenticate the original webhook before invoking this method.
    A successful return follows the database commit, not a delivery attempt.
    """
    if not message.id or len(message.id) > 255:
        raise ValueError("Invalid provider message identifier")
    if (
        not phone_number_id.isascii()
        or not phone_number_id.isdecimal()
        or len(phone_number_id) > 32
    ):
        raise ValueError("Invalid WhatsApp channel identifier")

    event_id = uuid.uuid4()
    relevant_contacts = [contact for contact in contacts or [] if contact.wa_id == message.from_]
    payload = {
        "phone_number_id": phone_number_id,
        "message": message.model_dump(mode="json", by_alias=True),
        "contacts": [
            contact.model_dump(mode="json", by_alias=True) for contact in relevant_contacts
        ],
    }
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    async with protect_ingestion(tenant):
        envelope = await cipher.encrypt(
            plaintext, tenant_id=tenant.id, purpose=PURPOSE, record_id=event_id
        )
        async with get_session_factory()() as session:
            current = (
                await session.execute(
                    select(Tenant).where(Tenant.id == tenant.id).with_for_update()
                )
            ).scalar_one_or_none()
            if (
                current is None
                or current.status != TenantStatus.active
                or (current.whatsapp_config or {}).get("phone_number_id") != phone_number_id
            ):
                raise TenantInactiveError("WhatsApp channel is inactive or has changed")
            statement = (
                insert(WhatsAppInboxEvent)
                .values(
                    id=event_id,
                    tenant_id=tenant.id,
                    phone_number_id=phone_number_id,
                    provider_message_id=message.id,
                    ciphertext=envelope.ciphertext,
                    key_version=envelope.version,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "provider_message_id"])
                .returning(WhatsAppInboxEvent.id)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none() is not None
            await session.commit()
            return inserted
