"""Conservative reconciliation of explicit pre-ordering STOP commands.

Staged only. No message is sent and the operator must still review the
uncertain outcome afterwards. Unsupported or redacted records stay blocked.
"""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.database import get_session_factory, set_tenant_search_path
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import protect_ingestion
from app.models.audit import AuditLog
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.schemas.whatsapp import IncomingMessage
from app.services.contact.consent import lock_and_opt_out
from app.services.contact.segmentation import SegmentationService
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.whatsapp.conversation_lock import lock_for_acceptance


class LegacyReconciliationError(ValueError):
    """Record cannot be safely reconciled without additional review."""


async def reconcile_legacy_text(
    tenant: TenantContext, event_id: uuid.UUID, actor_id: uuid.UUID, *,
    cipher: VersionedEnvelopeService,
) -> bool:
    """Identify a legacy text and atomically apply STOP if present.

    Returns whether STOP was applied. Never retries or resolves the event.
    Payload and channel are checked twice around lock acquisition so retention,
    tenant changes and concurrent reconciliations fail closed.
    """
    factory = get_session_factory()
    async with protect_ingestion(tenant):
        async with factory() as session:
            row = (await session.execute(
                select(WhatsAppInboxEvent).where(
                    WhatsAppInboxEvent.id == event_id,
                    WhatsAppInboxEvent.tenant_id == tenant.id,
                )
            )).scalar_one_or_none()
            if (row is None or row.sender_fingerprint is not None
                    or row.state not in {"uncertain", "follow_up"} or row.redacted_at is not None):
                raise LegacyReconciliationError("Événement indisponible pour rapprochement")
            channel, provider_id = row.phone_number_id, row.provider_message_id
            ciphertext, version = row.ciphertext, row.key_version

        plaintext = await cipher.decrypt(
            VersionedEnvelope(version, ciphertext), tenant_id=tenant.id,
            purpose="wa_inbox", record_id=event_id,
        )
        try:
            payload = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LegacyReconciliationError("Contenu du message illisible") from None
        if not isinstance(payload, dict) or payload.get("phone_number_id") != channel:
            raise LegacyReconciliationError("Canal du message incohérent")
        try:
            message = IncomingMessage.model_validate(payload.get("message"))
        except ValidationError:
            # Pydantic exceptions can contain private message contents.
            raise LegacyReconciliationError("Message invalide : examen spécifique requis") from None
        if message.id != provider_id or message.type != "text" or not message.text:
            raise LegacyReconciliationError("Message non textuel ou incohérent : examen spécifique requis")
        is_stop = SegmentationService.is_stop_command(message.text.body)
        if not is_stop:
            # An arbitrary sentence may still express an opt-out. Without a
            # reviewed interpretation it is unsafe to mark this stream known.
            raise LegacyReconciliationError("Message sans commande STOP reconnue : examen spécifique requis")
        fingerprint = await cipher.whatsapp_sender_fingerprint(
            tenant_id=tenant.id, channel_id=channel, sender_id=message.from_,
        )
        async with factory() as session:
            current = (await session.execute(
                select(Tenant).where(Tenant.id == tenant.id).with_for_update(read=True)
            )).scalar_one_or_none()
            if (current is None or current.slug != tenant.slug or current.status != TenantStatus.active
                    or (current.whatsapp_config or {}).get("phone_number_id") != channel):
                raise LegacyReconciliationError("Institution ou canal modifié")
            await lock_for_acceptance(session, tenant.id, fingerprint)
            event = (await session.execute(
                select(WhatsAppInboxEvent).where(
                    WhatsAppInboxEvent.id == event_id, WhatsAppInboxEvent.tenant_id == tenant.id,
                ).with_for_update()
            )).scalar_one_or_none()
            if (event is None or event.sender_fingerprint is not None
                    or event.state not in {"uncertain", "follow_up"} or event.redacted_at is not None
                    or event.phone_number_id != channel or event.provider_message_id != provider_id
                    or event.ciphertext != ciphertext or event.key_version != version):
                raise LegacyReconciliationError("Événement modifié pendant le rapprochement")
            if is_stop:
                await set_tenant_search_path(session, tenant.db_schema)
                contact_id = await lock_and_opt_out(session, message.from_)
                session.add(AuditLog(
                    tenant_slug=tenant.slug, user_id=actor_id, user_type="admin",
                    action="opt_in_change", resource_type="contact", resource_id=str(contact_id),
                    details={"new_status": "opted_out", "source": "legacy_user_stop"},
                ))
            event.sender_fingerprint = fingerprint
            event.is_opt_out = is_stop
            event.updated_at = func.clock_timestamp()
            session.add(AuditLog(
                tenant_slug=tenant.slug, user_id=actor_id, user_type="admin",
                action="wa_legacy_reconcile", resource_type="whatsapp_inbox_event",
                resource_id=str(event.id), details={"stop_applied": is_stop},
            ))
            await session.commit()
            return is_stop
