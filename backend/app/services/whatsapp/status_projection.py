"""Staged transactional projection of delivery events into tenant messages."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.core.database import get_session_factory, set_tenant_search_path
from app.core.exceptions import TenantInactiveError
from app.core.tenant import TenantResolver
from app.core.tenant_lifecycle import protect_ingestion
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import MessageDirection, TenantStatus
from app.models.tenant import Tenant
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.whatsapp import StatusInfo
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.whatsapp.status_inbox import PURPOSE
from app.services.whatsapp.status_policy import decide_status


async def apply_status_event(event_id: uuid.UUID, *, cipher: VersionedEnvelopeService) -> str:
    """Atomically project one event; wait if the outbound message is not yet known.

    Callers should process bounded batches and monitor waiting/uncertain events.
    No provider-side side effect is performed by this operation.
    """
    factory = get_session_factory()
    async with factory() as session:
        identity = (
            await session.execute(
                select(WhatsAppStatusEvent.tenant_id).where(WhatsAppStatusEvent.id == event_id)
            )
        ).scalar_one_or_none()
    if identity is None:
        return "missing"
    initial = await TenantResolver.from_tenant_id_header(str(identity))
    async with protect_ingestion(initial), factory() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.id == identity).with_for_update(read=True)
            )
        ).scalar_one_or_none()
        event = (
            await session.execute(
                select(WhatsAppStatusEvent)
                .where(
                    WhatsAppStatusEvent.id == event_id, WhatsAppStatusEvent.tenant_id == identity
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if event is None:
            return "missing"
        if event.state != "pending":
            return event.state
        database_now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
        if event.next_attempt_at > database_now:
            return "deferred"
        if (
            tenant is None
            or tenant.slug != initial.slug
            or tenant.status != TenantStatus.active
            or (tenant.whatsapp_config or {}).get("phone_number_id") != event.phone_number_id
        ):
            raise TenantInactiveError("WhatsApp channel is inactive or has changed")
        plaintext = await cipher.decrypt(
            VersionedEnvelope(event.key_version, event.ciphertext),
            tenant_id=identity,
            purpose=PURPOSE,
            record_id=event.id,
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict) or payload.get("phone_number_id") != event.phone_number_id:
            raise ValueError("Status channel mismatch")
        status = StatusInfo.model_validate(payload.get("status"))
        await set_tenant_search_path(session, initial.db_schema)
        matched = (
            await session.execute(
                select(Message, Contact.phone)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .join(Contact, Contact.id == Conversation.contact_id)
                .where(
                    Message.whatsapp_message_id == status.id,
                    Message.direction == MessageDirection.outbound,
                )
                .with_for_update(of=Message)
            )
        ).one_or_none()
        if matched is None:
            event.attempts += 1
            event.updated_at = database_now
            if event.attempts >= 288:
                event.state = "uncertain"
                result = "uncertain"
            else:
                event.next_attempt_at = database_now + timedelta(minutes=5)
                result = "waiting"
            await session.commit()
            return result
        message, contact_phone = matched
        # Provider recipient IDs and stored E.164 numbers may differ by a
        # leading '+'. Other differences are ambiguous: do not attach a
        # delivery result to a different citizen's conversation.
        recipient = status.recipient_id.removeprefix("+")
        stored = contact_phone.removeprefix("+") if contact_phone else ""
        if not (recipient.isascii() and recipient.isdecimal() and recipient == stored):
            event.state = "uncertain"
            event.updated_at = func.now()
            await session.commit()
            return "uncertain"
        metadata = dict(message.metadata_ or {})
        decision = decide_status(metadata.get("delivery_state"), status.status)
        if decision.uncertain:
            # Preserve the last verified state while making the conflict
            # visible to consumers of this message. Human review does not
            # currently clear this flag automatically.
            metadata["delivery_review_required"] = True
            message.metadata_ = metadata
            event.state = "uncertain"
        else:
            metadata["delivery_state"] = decision.state
            message.metadata_ = metadata
            event.state = "applied"
        event.updated_at = func.now()
        await session.commit()
        return event.state
