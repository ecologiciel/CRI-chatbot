"""Fenced execution of staged agent replies; not connected to a worker.

One provider attempt is permitted. An ambiguous result is quarantined; a
provider call already in flight cannot be recalled or made exactly once.
"""

from __future__ import annotations

import asyncio
import hmac

from sqlalchemy import func, select, text

from app.core.database import get_session_factory, set_tenant_search_path
from app.core.tenant import TenantResolver
from app.core.tenant_lifecycle import lock_active_tenant
from app.models.admin import Admin
from app.models.agent_reply_outbox import AgentReplyOutboxEvent
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import (
    AdminRole,
    EscalationStatus,
    MessageDirection,
    MessageType,
    OptInStatus,
    TenantStatus,
)
from app.models.escalation import Escalation
from app.models.tenant import Tenant
from app.services.contact.phone_identity import phone_variants
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.escalation.reply_leases import AgentReplyClaim, AgentReplyLeaseLostError
from app.services.escalation.reply_outbox import PURPOSE
from app.services.whatsapp.sender import WhatsAppSenderService


class AgentReplyPreconditionError(RuntimeError):
    """The reply context changed; quarantine for human review."""


async def execute_agent_reply(
    claim: AgentReplyClaim, *, cipher: VersionedEnvelopeService, sender: WhatsAppSenderService,
    timeout_seconds: int = 40,
) -> str:
    """Attempt a claimed reply once and atomically record the observed result.

    On precondition, timeout or commit failure the claim remains processing;
    the lease reaper must quarantine it as uncertain, never retry it.
    """
    if not 1 <= timeout_seconds <= 60:
        raise ValueError("Invalid reply timeout")
    factory = get_session_factory()
    async with asyncio.timeout(timeout_seconds):
        async with factory() as session:
            snapshot = (await session.execute(
                select(AgentReplyOutboxEvent).where(
                    AgentReplyOutboxEvent.id == claim.id, AgentReplyOutboxEvent.tenant_id == claim.tenant_id,
                )
            )).scalar_one_or_none()
            if snapshot is None:
                raise AgentReplyLeaseLostError("Agent reply unavailable")
            identity = (snapshot.actor_id, snapshot.escalation_id, snapshot.conversation_id,
                        snapshot.contact_id, snapshot.phone_number_id, snapshot.recipient_fingerprint,
                        snapshot.ciphertext, snapshot.key_version)
        tenant_context = await TenantResolver.from_tenant_id_header(str(claim.tenant_id))
        async with factory() as session:
            await lock_active_tenant(session, tenant_context)
            tenant = (await session.execute(
                select(Tenant).where(Tenant.id == claim.tenant_id).with_for_update(read=True)
            )).scalar_one_or_none()
            actor = (await session.execute(
                select(Admin.id).where(
                    Admin.id == identity[0], Admin.tenant_id == claim.tenant_id, Admin.is_active.is_(True),
                    Admin.role.in_([AdminRole.supervisor, AdminRole.admin_tenant]),
                ).with_for_update(read=True)
            )).scalar_one_or_none()
            if (tenant is None or tenant.slug != tenant_context.slug or tenant.status != TenantStatus.active
                    or actor is None or (tenant.whatsapp_config or {}).get("phone_number_id") != identity[4]):
                raise AgentReplyPreconditionError("Institution, agent ou canal indisponible")
            schema = tenant_context.db_schema
            tables = (await session.execute(text(
                "SELECT to_regclass(:contacts), to_regclass(:conversations), to_regclass(:escalations), to_regclass(:messages)"
            ), {"contacts": f"{schema}.contacts", "conversations": f"{schema}.conversations",
                "escalations": f"{schema}.escalations", "messages": f"{schema}.messages"})).one()
            if any(table is None for table in tables):
                raise AgentReplyPreconditionError("Schéma institutionnel indisponible")
            session.sync_session.info["tenant_schema"] = schema
            await set_tenant_search_path(session, schema)
            escalation = (await session.execute(
                select(Escalation).where(Escalation.id == identity[1]).with_for_update()
            )).scalar_one_or_none()
            if (escalation is None or escalation.conversation_id != identity[2]
                    or escalation.status not in {EscalationStatus.assigned, EscalationStatus.in_progress}):
                raise AgentReplyPreconditionError("Escalade indisponible")
            conversation = (await session.execute(
                select(Conversation).where(Conversation.id == identity[2]).with_for_update()
            )).scalar_one_or_none()
            if conversation is None or conversation.contact_id != identity[3]:
                raise AgentReplyPreconditionError("Conversation modifiée")
            contact = (await session.execute(
                select(Contact).where(Contact.id == identity[3]).with_for_update()
            )).scalar_one_or_none()
            if contact is None or contact.opt_in_status == OptInStatus.opted_out:
                raise AgentReplyPreconditionError("Contact ou consentement indisponible")
            variants = phone_variants(contact.phone)
            if len(variants) != 2:
                raise AgentReplyPreconditionError("Contact non identifiable")
            fingerprint = await cipher.whatsapp_sender_fingerprint(
                tenant_id=claim.tenant_id, channel_id=identity[4], sender_id=variants[0], session=session,
            )
            if not hmac.compare_digest(fingerprint, identity[5]):
                raise AgentReplyPreconditionError("Destinataire modifié")
            event = (await session.execute(
                select(AgentReplyOutboxEvent).where(
                    AgentReplyOutboxEvent.id == claim.id, AgentReplyOutboxEvent.tenant_id == claim.tenant_id,
                    AgentReplyOutboxEvent.state == "processing", AgentReplyOutboxEvent.lease_token == claim.token,
                    AgentReplyOutboxEvent.lease_until > func.clock_timestamp(),
                ).with_for_update()
            )).scalar_one_or_none()
            if event is None:
                raise AgentReplyLeaseLostError("Agent reply lease unavailable")
            actual = (event.actor_id, event.escalation_id, event.conversation_id, event.contact_id,
                      event.phone_number_id, event.recipient_fingerprint, event.ciphertext, event.key_version)
            if event.redacted_at is not None or actual != identity:
                raise AgentReplyPreconditionError("Demande modifiée ou expirée")
            plaintext = await cipher.decrypt(
                VersionedEnvelope(event.key_version, event.ciphertext), tenant_id=claim.tenant_id,
                purpose=PURPOSE, record_id=event.id, session=session,
            )
            try:
                message = plaintext.decode("utf-8")
            except UnicodeDecodeError:
                raise AgentReplyPreconditionError("Message illisible") from None
            if not message.strip() or len(message) > 4000:
                raise AgentReplyPreconditionError("Message invalide")
            # Recheck against database time immediately before the provider
            # call. Holding the row prevents any other worker from finalizing.
            live = await session.scalar(
                select(AgentReplyOutboxEvent.lease_until > func.clock_timestamp())
                .where(AgentReplyOutboxEvent.id == event.id)
            )
            if not live:
                raise AgentReplyLeaseLostError("Agent reply lease expired")
            provider_id = None
            try:
                observed = await sender.send_text(TenantResolver._build_context(tenant), contact.phone, message)
                if isinstance(observed, str) and 0 < len(observed) <= 100:
                    provider_id = observed
            except Exception:
                # Provider errors and timeouts cannot prove non-delivery.
                pass
            live = await session.scalar(
                select(AgentReplyOutboxEvent.lease_until > func.clock_timestamp())
                .where(AgentReplyOutboxEvent.id == event.id)
            )
            if not live:
                # The provider may already have accepted. Roll back and let
                # the reaper quarantine the expired claim rather than resend.
                raise AgentReplyLeaseLostError("Agent reply lease expired during provider call")
            state = "accepted" if provider_id else "uncertain"
            event.state = state
            event.outcome_code = "provider_accepted" if provider_id else "provider_unconfirmed"
            event.provider_message_id = provider_id
            event.lease_token = None
            event.lease_until = None
            event.updated_at = func.clock_timestamp()
            session.add(Message(
                conversation_id=conversation.id, direction=MessageDirection.outbound, type=MessageType.text,
                content=message, whatsapp_message_id=provider_id,
                metadata_={"delivery_state": "accepted" if provider_id else "unconfirmed",
                           "agent_reply_event_id": str(event.id)},
            ))
            session.add(AuditLog(
                tenant_slug=tenant.slug, user_id=identity[0], user_type="admin",
                action="agent_reply_sent" if provider_id else "agent_reply_unknown",
                resource_type="agent_reply", resource_id=str(event.id),
            ))
            await session.commit()
            return state
