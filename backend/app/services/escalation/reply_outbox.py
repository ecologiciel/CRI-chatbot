"""Register encrypted agent replies idempotently; no provider send is performed.

Staged only. A future worker must recheck tenant, channel, contact, consent and
claim ownership before sending. A lost provider response is never a safe retry.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_session_factory
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import lock_active_tenant
from app.models.admin import Admin
from app.models.agent_reply_outbox import AgentReplyOutboxEvent
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.enums import AdminRole, EscalationStatus, OptInStatus, TenantStatus
from app.models.escalation import Escalation
from app.models.tenant import Tenant
from app.services.contact.phone_identity import phone_variants
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService

PURPOSE = "agent_reply"


class AgentReplyConflictError(ValueError):
    """Request identity or current state is incompatible with a safe enqueue."""


@dataclass(frozen=True, slots=True)
class RegisteredReply:
    id: uuid.UUID
    state: str
    created: bool


async def register_agent_reply(
    tenant: TenantContext,
    escalation_id: uuid.UUID,
    actor_id: uuid.UUID,
    request_key: uuid.UUID,
    message: str,
    *,
    cipher: VersionedEnvelopeService,
) -> RegisteredReply:
    """Persist one intention and its audit atomically, or return its replay.

    The caller must authenticate and authorize the actor. Reuse of a key for a
    different actor, escalation or text is rejected without exposing content.
    Existing requests are never automatically resent by this function.
    """
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise ValueError("Invalid reply text")
    try:
        plaintext = message.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Invalid reply text") from None
    if len(plaintext) > 16000:
        raise ValueError("Invalid reply text")
    factory = get_session_factory()
    async with factory() as session:
        await lock_active_tenant(session, tenant)
        current = (await session.execute(
            select(Tenant).where(Tenant.id == tenant.id).with_for_update(read=True)
        )).scalar_one_or_none()
        if current is None or current.slug != tenant.slug or current.status != TenantStatus.active:
            raise AgentReplyConflictError("Institution indisponible")
        actor = (await session.execute(
            select(Admin.id).where(
                Admin.id == actor_id, Admin.tenant_id == tenant.id, Admin.is_active.is_(True),
                Admin.role.in_([AdminRole.supervisor, AdminRole.admin_tenant]),
            ).with_for_update(read=True)
        )).scalar_one_or_none()
        if actor is None:
            raise AgentReplyConflictError("Agent indisponible ou non autorisé")

        async def existing_reply() -> RegisteredReply | None:
            event = (await session.execute(
                select(AgentReplyOutboxEvent).where(
                    AgentReplyOutboxEvent.tenant_id == tenant.id,
                    AgentReplyOutboxEvent.request_key == request_key,
                ).with_for_update()
            )).scalar_one_or_none()
            if event is None:
                return None
            if event.actor_id != actor_id or event.escalation_id != escalation_id or event.redacted_at is not None:
                raise AgentReplyConflictError("Référence de demande incompatible ou expirée")
            previous = await cipher.decrypt(
                VersionedEnvelope(event.key_version, event.ciphertext),
                tenant_id=tenant.id, purpose=PURPOSE, record_id=event.id, session=session,
            )
            if not hmac.compare_digest(previous, plaintext):
                raise AgentReplyConflictError("Référence de demande incompatible ou expirée")
            return RegisteredReply(event.id, event.state, False)

        replay = await existing_reply()
        if replay is not None:
            return replay
        # Only constant, validated tenant slugs are interpolated into a local
        # search path by TenantContext; never share a tenant-scoped session.
        session.sync_session.info["tenant_schema"] = tenant.db_schema
        # A transaction has already begun for the shared tenant row, so the
        # session's after_begin hook will not run again until the next one.
        tables = (await session.execute(text(
            "SELECT to_regclass(:contacts), to_regclass(:conversations), to_regclass(:escalations)"
        ), {
            "contacts": f"{tenant.db_schema}.contacts",
            "conversations": f"{tenant.db_schema}.conversations",
            "escalations": f"{tenant.db_schema}.escalations",
        })).one()
        if any(table is None for table in tables):
            raise AgentReplyConflictError("Schéma institutionnel indisponible")
        await session.execute(text("SELECT set_config('search_path', :path, true)"), {"path": f"{tenant.db_schema}, public"})
        escalation = (await session.execute(
            select(Escalation).where(Escalation.id == escalation_id).with_for_update()
        )).scalar_one_or_none()
        # A concurrent request may have committed while this transaction was
        # waiting for the escalation row. Replay remains valid even if the
        # escalation has since been closed.
        replay = await existing_reply()
        if replay is not None:
            return replay
        if escalation is None or escalation.status not in {EscalationStatus.assigned, EscalationStatus.in_progress}:
            raise AgentReplyConflictError("Escalade indisponible pour réponse")
        # Different escalations may reference the same conversation. This
        # lock serializes acceptance order across all of them until commit.
        conversation = (await session.execute(
            select(Conversation).where(Conversation.id == escalation.conversation_id).with_for_update()
        )).scalar_one_or_none()
        if conversation is None:
            raise AgentReplyConflictError("Conversation indisponible")
        # Serialize new intentions across agents and escalations.  In
        # particular, a response queued behind an ambiguous send must not be
        # released later by a review the author did not anticipate. Replays
        # of the *same* request remain available above.
        outstanding = (await session.execute(
            select(AgentReplyOutboxEvent.id).where(
                AgentReplyOutboxEvent.tenant_id == tenant.id,
                AgentReplyOutboxEvent.conversation_id == conversation.id,
                AgentReplyOutboxEvent.state.in_(["pending", "processing", "uncertain", "follow_up"]),
            ).limit(1)
        )).scalar_one_or_none()
        if outstanding is not None:
            raise AgentReplyConflictError("Une réponse de cette conversation est déjà en cours ou à examiner")
        contact = (await session.execute(
            select(Contact).where(Contact.id == conversation.contact_id).with_for_update()
        )).scalar_one_or_none()
        config = current.whatsapp_config or {}
        channel = config.get("phone_number_id", "")
        variants = phone_variants(contact.phone) if contact is not None else ()
        if (contact is None or contact.opt_in_status == OptInStatus.opted_out or len(variants) != 2
                or not isinstance(channel, str) or not channel.isascii() or not channel.isdecimal()
                or len(channel) > 32 or not config.get("access_token")):
            raise AgentReplyConflictError("Contact, consentement ou canal indisponible")
        fingerprint = await cipher.whatsapp_sender_fingerprint(
            tenant_id=tenant.id, channel_id=channel, sender_id=variants[0],
            session=session,
        )
        event_id = uuid.uuid4()
        envelope = await cipher.encrypt(plaintext, tenant_id=tenant.id, purpose=PURPOSE, record_id=event_id, session=session)
        statement = (
            insert(AgentReplyOutboxEvent)
            .values(id=event_id, tenant_id=tenant.id, request_key=request_key, actor_id=actor_id,
                    escalation_id=escalation_id, conversation_id=escalation.conversation_id,
                    contact_id=contact.id, phone_number_id=channel, recipient_fingerprint=fingerprint,
                    ciphertext=envelope.ciphertext, key_version=envelope.version)
            .on_conflict_do_nothing(index_elements=["tenant_id", "request_key"])
            .returning(AgentReplyOutboxEvent.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is None:
            replay = await existing_reply()
            if replay is None:
                raise AgentReplyConflictError("Référence de demande indisponible")
            return replay
        session.add(AuditLog(
            tenant_slug=tenant.slug, user_id=actor_id, user_type="admin", action="agent_reply_queued",
            resource_type="agent_reply", resource_id=str(event_id),
            details={"escalation_id": str(escalation_id)},
        ))
        await session.commit()
        return RegisteredReply(event_id, "pending", True)
