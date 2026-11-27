"""Persist one authenticated WhatsApp message in an encrypted inbox.

This service is staged only: the webhook and worker do not call it yet.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_session_factory
from app.core.exceptions import TenantInactiveError
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import protect_ingestion
from app.models.audit import AuditLog
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.schemas.whatsapp import ContactInfo, IncomingMessage
from app.services.contact.consent import lock_and_opt_out
from app.services.contact.segmentation import SegmentationService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.conversation_lock import lock_for_acceptance

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
    is_opt_out = bool(
        message.type == "text" and message.text and SegmentationService.is_stop_command(message.text.body)
    )

    async with protect_ingestion(tenant):
        sender_fingerprint = await cipher.whatsapp_sender_fingerprint(
            tenant_id=tenant.id, channel_id=phone_number_id, sender_id=message.from_
        )
        envelope = await cipher.encrypt(
            plaintext, tenant_id=tenant.id, purpose=PURPOSE, record_id=event_id
        )
        async with get_session_factory()() as session:
            current = (
                await session.execute(
                    select(Tenant).where(Tenant.id == tenant.id).with_for_update(read=True)
                )
            ).scalar_one_or_none()
            if (
                current is None
                or current.status != TenantStatus.active
                or (current.whatsapp_config or {}).get("phone_number_id") != phone_number_id
            ):
                raise TenantInactiveError("WhatsApp channel is inactive or has changed")
            # Serializing acceptance with claims makes sequence order reflect
            # commit order within this conversation. Provider arrival order can
            # still differ from the order in which the user sent messages.
            await lock_for_acceptance(session, tenant.id, sender_fingerprint)
            statement = (
                insert(WhatsAppInboxEvent)
                .values(
                    id=event_id,
                    tenant_id=tenant.id,
                    phone_number_id=phone_number_id,
                    sender_fingerprint=sender_fingerprint,
                    is_opt_out=is_opt_out,
                    provider_message_id=message.id,
                    ciphertext=envelope.ciphertext,
                    key_version=envelope.version,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "provider_message_id"])
                .returning(WhatsAppInboxEvent.id)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none() is not None
            if inserted and is_opt_out:
                # Commit the consent change with the inbox record before ACK.
                # Provider sends already holding the contact row may finish;
                # subsequent consent-checked sends see the committed opt-out.
                await session.execute(
                    text("SELECT set_config('search_path', :path, true)"),
                    {"path": f"{tenant.db_schema}, public"},
                )
                contact_id = await lock_and_opt_out(session, message.from_)
                session.add(AuditLog(
                    tenant_slug=tenant.slug, user_type="system", action="opt_in_change",
                    resource_type="contact", resource_id=str(contact_id),
                    details={"new_status": "opted_out", "source": "user_stop"},
                ))
            await session.commit()
            return inserted
