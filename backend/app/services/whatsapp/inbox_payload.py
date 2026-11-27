"""Validate the authenticated context of a staged WhatsApp inbox claim.

This module is not yet connected to the production webhook or a worker.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from app.schemas.whatsapp import ContactInfo, IncomingMessage
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.whatsapp.inbox import PURPOSE
from app.services.whatsapp.inbox_leases import InboxClaim


@dataclass(frozen=True, slots=True)
class InboxPayload:
    message: IncomingMessage
    contacts: list[ContactInfo]


async def decrypt_claim(claim: InboxClaim, cipher: VersionedEnvelopeService) -> InboxPayload:
    """Decrypt and bind message and channel to the claimed database record."""
    plaintext = await cipher.decrypt(
        VersionedEnvelope(version=claim.key_version, ciphertext=claim.ciphertext),
        tenant_id=claim.tenant_id,
        purpose=PURPOSE,
        record_id=claim.id,
    )
    payload = json.loads(plaintext)
    if not isinstance(payload, dict) or payload.get("phone_number_id") != claim.phone_number_id:
        raise ValueError("Inbox channel mismatch")
    message = IncomingMessage.model_validate(payload.get("message"))
    if message.id != claim.provider_message_id:
        raise ValueError("Inbox message identifier mismatch")
    expected = await cipher.whatsapp_sender_fingerprint(
        tenant_id=claim.tenant_id, channel_id=claim.phone_number_id, sender_id=message.from_
    )
    if not claim.sender_fingerprint or not hmac.compare_digest(expected, claim.sender_fingerprint):
        raise ValueError("Inbox conversation identifier mismatch")
    raw_contacts = payload.get("contacts")
    if not isinstance(raw_contacts, list):
        raise ValueError("Invalid inbox contacts")
    contacts = [ContactInfo.model_validate(contact) for contact in raw_contacts]
    if any(contact.wa_id != message.from_ for contact in contacts):
        raise ValueError("Inbox contact mismatch")
    return InboxPayload(message=message, contacts=contacts)
