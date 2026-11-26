"""Staged authenticated WhatsApp intake, deliberately not exposed by the API.

Delivery statuses still lack durable storage. Until they are implemented,
mixed batches are rejected before any writes instead of being acknowledged
as if those statuses had been processed.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.tenant import TenantResolver
from app.schemas.whatsapp import WhatsAppWebhookPayload
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.inbox import persist_incoming_message
from app.services.whatsapp.webhook import WhatsAppWebhookService


class UnsupportedInboxEventError(ValueError):
    """An event type cannot yet be durably acknowledged."""


async def persist_authenticated_webhook(raw_body: bytes, signature: str | None) -> None:
    """Return only after every supported message has committed or was a duplicate."""
    WhatsAppWebhookService._validate_hmac_signature(raw_body, signature)
    payload = WhatsAppWebhookPayload.model_validate_json(raw_body)
    changes = [change for entry in payload.entry for change in entry.changes]
    if payload.object != "whatsapp_business_account" or not changes:
        raise UnsupportedInboxEventError("Unsupported WhatsApp event")
    for change in changes:
        if change.field != "messages" or change.value.statuses or not change.value.messages:
            raise UnsupportedInboxEventError("WhatsApp event type is not yet durably supported")

    cipher = VersionedEnvelopeService(get_session_factory(), get_settings().kms_master_key)
    for change in changes:
        phone_number_id = change.value.metadata.phone_number_id
        tenant = await TenantResolver.from_phone_number_id(phone_number_id)
        for message in change.value.messages or []:
            await persist_incoming_message(
                tenant, phone_number_id, message, change.value.contacts, cipher=cipher
            )
