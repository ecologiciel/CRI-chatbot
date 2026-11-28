"""Staged authenticated WhatsApp intake, deliberately not exposed by the API.

Delivery statuses are stored separately; applying them to conversations is
not yet implemented, so this intake remains disconnected from production.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.tenant import TenantContext, TenantResolver
from app.schemas.whatsapp import WhatsAppWebhookPayload
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.inbox import persist_incoming_message
from app.services.whatsapp.status_inbox import persist_delivery_status
from app.services.whatsapp.tenant_webhook_auth import authenticate_tenant_payload
from app.services.whatsapp.webhook import WhatsAppWebhookService


class UnsupportedInboxEventError(ValueError):
    """An event type cannot yet be durably acknowledged."""


async def persist_tenant_authenticated_webhook(
    tenant: TenantContext, raw_body: bytes, signature: str | None,
) -> None:
    """Persist a tenant-bound batch; each write rechecks the signing secret.

    There is deliberately no HTTP route yet. A partially committed batch must
    be retried; per-event idempotency prevents duplicate inbox records.
    """
    payload = authenticate_tenant_payload(tenant, raw_body, signature)
    master_key = get_settings().kms_master_key
    cipher = VersionedEnvelopeService(get_session_factory(), master_key)
    for entry in payload.entry:
        for change in entry.changes:
            value = change.value
            phone = value.metadata.phone_number_id
            for message in value.messages or []:
                await persist_incoming_message(
                    tenant, phone, message, value.contacts, cipher=cipher,
                    require_current_signing_secret=True,
                )
            for status in value.statuses or []:
                await persist_delivery_status(
                    tenant, phone, status, cipher=cipher,
                    fingerprint_key=bytes.fromhex(master_key),
                    require_current_signing_secret=True,
                )


async def persist_authenticated_webhook(raw_body: bytes, signature: str | None) -> None:
    """Return only after every supported message has committed or was a duplicate."""
    WhatsAppWebhookService._validate_hmac_signature(raw_body, signature)
    payload = WhatsAppWebhookPayload.model_validate_json(raw_body)
    changes = [change for entry in payload.entry for change in entry.changes]
    if payload.object != "whatsapp_business_account" or not changes:
        raise UnsupportedInboxEventError("Unsupported WhatsApp event")
    for change in changes:
        if change.field != "messages" or not (change.value.messages or change.value.statuses):
            raise UnsupportedInboxEventError("WhatsApp event type is not yet durably supported")

    master_key = get_settings().kms_master_key
    cipher = VersionedEnvelopeService(get_session_factory(), master_key)
    for change in changes:
        phone_number_id = change.value.metadata.phone_number_id
        tenant = await TenantResolver.from_phone_number_id(phone_number_id)
        for message in change.value.messages or []:
            await persist_incoming_message(
                tenant, phone_number_id, message, change.value.contacts, cipher=cipher
            )
        for status in change.value.statuses or []:
            await persist_delivery_status(
                tenant,
                phone_number_id,
                status,
                cipher=cipher,
                fingerprint_key=bytes.fromhex(master_key),
            )
