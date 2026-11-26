"""Persist encrypted delivery notifications before acknowledging a webhook.

Staged only. Deduplication uses a keyed digest; master-key rotation can
create duplicate records, so the eventual status projector must be idempotent.
"""

from __future__ import annotations

import hashlib
import hmac
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
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.whatsapp import StatusInfo
from app.services.crypto.versioned_envelope import VersionedEnvelopeService

PURPOSE = "wa_status"


async def persist_delivery_status(
    tenant: TenantContext,
    phone_number_id: str,
    status: StatusInfo,
    *,
    cipher: VersionedEnvelopeService,
    fingerprint_key: bytes,
) -> bool:
    """Persist one authenticated notification or report an exact duplicate."""
    if len(fingerprint_key) != 32:
        raise ValueError("Invalid status fingerprint key")
    if (
        not phone_number_id.isascii()
        or not phone_number_id.isdecimal()
        or len(phone_number_id) > 32
    ):
        raise ValueError("Invalid WhatsApp channel identifier")
    if not status.id or len(status.id) > 255 or not status.status or len(status.status) > 64:
        raise ValueError("Invalid WhatsApp status identifier")
    if (
        not status.timestamp.isascii()
        or not status.timestamp.isdecimal()
        or len(status.timestamp) > 20
    ):
        raise ValueError("Invalid WhatsApp status timestamp")
    payload = {"phone_number_id": phone_number_id, "status": status.model_dump(mode="json")}
    plaintext = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    fingerprint = hmac.new(
        fingerprint_key, b"wa-status-v1:" + tenant.id.bytes + plaintext, hashlib.sha256
    ).hexdigest()
    event_id = uuid.uuid4()
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
                insert(WhatsAppStatusEvent)
                .values(
                    id=event_id,
                    tenant_id=tenant.id,
                    phone_number_id=phone_number_id,
                    fingerprint=fingerprint,
                    ciphertext=envelope.ciphertext,
                    key_version=envelope.version,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "fingerprint"])
                .returning(WhatsAppStatusEvent.id)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none() is not None
            await session.commit()
            return inserted
