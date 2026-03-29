"""EscalationService — human agent escalation management (Phase 2).

Covers the 6 trigger scenarios defined in the CPS:
1. explicit_request — user asks to speak to a human
2. rag_failure — consecutive low-confidence RAG responses
3. sensitive_topic — detected by IntentDetector
4. negative_feedback — thumbs-down + "talk to agent"
5. otp_timeout — OTP timeout > 5 min (Phase 3 stub)
6. manual — triggered from back-office

Lifecycle: pending → assigned → in_progress → resolved / closed.
On creation, conversation.status is set to 'escalated'.
On closure, conversation.status returns to 'active' (auto mode).

All DB operations are tenant-scoped via tenant.db_session().
Redis pub/sub notifications are published for real-time BO updates.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import case, func, select, update

from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import (
    ConversationStatus,
    EscalationPriority,
    EscalationStatus,
    EscalationTrigger,
    MessageDirection,
    MessageType,
)
from app.models.escalation import Escalation
from app.schemas.audit import AuditLogCreate
from app.services.ai.gemini import GeminiService, get_gemini_service
from app.services.audit.service import AuditService, get_audit_service
from app.services.whatsapp.sender import WhatsAppSenderService

# Avoid circular import: orchestrator.__init__ → graph → escalation_handler → this module.
# ConversationState is a TypedDict used only for type hints.
# IntentType.ESCALADE is just the string "escalade".
_INTENT_ESCALADE = "escalade"

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Trilingual messages
# ---------------------------------------------------------------------------

TRANSITION_MESSAGES: dict[str, str] = {
    "fr": (
        "Un conseiller CRI va prendre le relais pour mieux vous "
        "accompagner. Veuillez patienter quelques instants. \U0001f64f"
    ),
    "ar": (
        "\u0633\u064a\u0642\u0648\u0645 \u0645\u0633\u062a\u0634\u0627\u0631 "
        "\u0645\u0646 \u0627\u0644\u0645\u0631\u0643\u0632 \u0627\u0644\u062c\u0647\u0648\u064a "
        "\u0644\u0644\u0627\u0633\u062a\u062b\u0645\u0627\u0631 \u0628\u0645\u062a\u0627\u0628\u0639\u0629 "
        "\u0637\u0644\u0628\u0643\u0645 \u0644\u0645\u0633\u0627\u0639\u062f\u062a\u0643\u0645 "
        "\u0628\u0634\u0643\u0644 \u0623\u0641\u0636\u0644. "
        "\u064a\u0631\u062c\u0649 \u0627\u0644\u0627\u0646\u062a\u0638\u0627\u0631 "
        "\u0644\u062d\u0638\u0627\u062a. \U0001f64f"
    ),
    "en": (
        "A CRI advisor will take over to better assist you. "
        "Please wait a moment. \U0001f64f"
    ),
}

CLOSURE_MESSAGES: dict[str, str] = {
    "fr": (
        "Merci, votre demande a \u00e9t\u00e9 trait\u00e9e par notre \u00e9quipe. "
        "N'h\u00e9sitez pas \u00e0 nous recontacter si besoin."
    ),
    "ar": (
        "\u0634\u0643\u0631\u0627\u064b\u060c \u062a\u0645\u062a "
        "\u0645\u0639\u0627\u0644\u062c\u0629 \u0637\u0644\u0628\u0643\u0645 "
        "\u0645\u0646 \u0637\u0631\u0641 \u0641\u0631\u064a\u0642\u0646\u0627. "
        "\u0644\u0627 \u062a\u062a\u0631\u062f\u062f\u0648\u0627 "
        "\u0641\u064a \u0627\u0644\u062a\u0648\u0627\u0635\u0644 "
        "\u0645\u0639\u0646\u0627 \u0645\u062c\u062f\u062f\u0627\u064b."
    ),
    "en": (
        "Thank you, your request has been handled by our team. "
        "Feel free to contact us again if needed."
    ),
}

ALREADY_ESCALATED_MESSAGES: dict[str, str] = {
    "fr": (
        "Votre demande est d\u00e9j\u00e0 en cours de traitement par un "
        "conseiller. Veuillez patienter, il vous r\u00e9pondra sous peu."
    ),
    "ar": (
        "\u0637\u0644\u0628\u0643\u0645 \u0642\u064a\u062f \u0627\u0644\u0645\u0639\u0627\u0644\u062c\u0629 "
        "\u0645\u0646 \u0637\u0631\u0641 \u0645\u0633\u062a\u0634\u0627\u0631. "
        "\u064a\u0631\u062c\u0649 \u0627\u0644\u0627\u0646\u062a\u0638\u0627\u0631\u060c "
        "\u0633\u064a\u062a\u0645 \u0627\u0644\u0631\u062f \u0639\u0644\u064a\u0643\u0645 "
        "\u0642\u0631\u064a\u0628\u064b\u0627."
    ),
    "en": (
        "Your request is already being handled by an advisor. "
        "Please wait, they will respond shortly."
    ),
}


class EscalationService:
    """Service for managing escalations to human CRI agents.

    Handles the full lifecycle: detection, creation, assignment,
    human response via WhatsApp, and closure with return to auto mode.

    Args:
        gemini: GeminiService for generating context summaries.
        sender: WhatsAppSenderService for human-agent responses.
        audit: AuditService for audit trail logging.
    """

    TRIGGER_PRIORITY_MAP: dict[EscalationTrigger, EscalationPriority] = {
        EscalationTrigger.explicit_request: EscalationPriority.high,
        EscalationTrigger.rag_failure: EscalationPriority.medium,
        EscalationTrigger.sensitive_topic: EscalationPriority.high,
        EscalationTrigger.negative_feedback: EscalationPriority.medium,
        EscalationTrigger.otp_timeout: EscalationPriority.low,
        EscalationTrigger.manual: EscalationPriority.medium,
    }

    LOW_CONFIDENCE_THRESHOLD: float = 0.5
    CONSECUTIVE_FAILURE_LIMIT: int = 2

    def __init__(
        self,
        gemini: GeminiService,
        sender: WhatsAppSenderService,
        audit: AuditService,
    ) -> None:
        self._gemini = gemini
        self._sender = sender
        self._audit = audit
        self._logger = logger.bind(service="escalation_service")

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    async def detect_escalation(
        self, state: dict,
    ) -> EscalationTrigger | None:
        """Analyze conversation state for escalation triggers.

        Checks the 6 scenarios in priority order:
        1. explicit_request — intent == "escalade"
        2. rag_failure — consecutive_low_confidence >= threshold
        3. sensitive_topic — intent flagged by IntentDetector
        4. negative_feedback — detected via message content after 👎
        5. otp_timeout — Phase 3 stub (always None)
        6. manual — not detected here (API-only)

        Args:
            state: Current LangGraph conversation state.

        Returns:
            The first matching EscalationTrigger, or None.
        """
        intent = state.get("intent", "")

        # 1. Explicit request
        if intent == _INTENT_ESCALADE:
            return EscalationTrigger.explicit_request

        # 2. RAG failure — consecutive low-confidence responses
        consecutive = state.get("consecutive_low_confidence", 0)
        if consecutive >= self.CONSECUTIVE_FAILURE_LIMIT:
            return EscalationTrigger.rag_failure

        # 3. Sensitive topic — detected upstream by IntentDetector
        # (IntentDetector sets intent to "escalade" for sensitive topics,
        #  so this is a secondary check on guard_message)
        guard_msg = state.get("guard_message")
        if guard_msg and "sensitive" in (guard_msg or "").lower():
            return EscalationTrigger.sensitive_topic

        # 4. Negative feedback + request to talk to agent
        query = (state.get("query") or "").lower()
        negative_keywords = [
            "parler", "agent", "humain", "conseiller",
            "talk", "human", "advisor",
            "\u0645\u0648\u0638\u0641", "\u0645\u0633\u062a\u0634\u0627\u0631",
            "\u0627\u0644\u062a\u062d\u062f\u062b",
        ]
        if any(kw in query for kw in negative_keywords):
            confidence = state.get("confidence", 1.0)
            if confidence < self.LOW_CONFIDENCE_THRESHOLD:
                return EscalationTrigger.negative_feedback

        # 5. OTP timeout — Phase 3 stub
        # Will be implemented when TrackingAgent is built

        # 6. Manual — not detected via state, only via API

        return None

    # ------------------------------------------------------------------
    # Conversation lookup
    # ------------------------------------------------------------------

    async def lookup_active_conversation(
        self, tenant: TenantContext, phone: str,
    ) -> uuid.UUID | None:
        """Find the active conversation for a phone number.

        Args:
            tenant: Tenant context for DB access.
            phone: User's phone number (E.164).

        Returns:
            Conversation UUID if found, None otherwise.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Conversation.id)
                .join(Contact, Conversation.contact_id == Contact.id)
                .where(
                    Contact.phone == phone,
                    Conversation.status.in_([
                        ConversationStatus.active,
                        ConversationStatus.escalated,
                    ]),
                )
                .order_by(Conversation.started_at.desc())
                .limit(1),
            )
            row = result.scalar_one_or_none()
        return row

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_escalation(
        self,
        conversation_id: uuid.UUID,
        trigger: EscalationTrigger,
        user_message: str | None,
        tenant: TenantContext,
    ) -> Escalation:
        """Create a new escalation and update conversation status.

        Steps:
        1. Generate context summary via Gemini
        2. Create Escalation record (status=pending)
        3. Update conversation.status = escalated
        4. Publish Redis notification
        5. Audit log

        Note: WhatsApp transition message is NOT sent here — it is
        set in state["response"] and sent by MessageHandler.

        Args:
            conversation_id: The conversation to escalate.
            trigger: Which of the 6 scenarios caused this.
            user_message: Last user message before escalation.
            tenant: Tenant context.

        Returns:
            The created Escalation record.
        """
        priority = self.TRIGGER_PRIORITY_MAP[trigger]

        # 1. Generate context summary (fire-and-forget on failure)
        context_summary = None
        try:
            context_summary = await self.generate_context_summary(
                conversation_id, tenant,
            )
        except Exception as exc:
            self._logger.warning(
                "context_summary_failed",
                error=str(exc),
                conversation_id=str(conversation_id),
                tenant=tenant.slug,
            )

        # 2. Create escalation + 3. Update conversation status
        async with tenant.db_session() as session:
            escalation = Escalation(
                conversation_id=conversation_id,
                trigger_type=trigger,
                priority=priority,
                context_summary=context_summary,
                user_message=user_message,
                status=EscalationStatus.pending,
            )
            session.add(escalation)

            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(status=ConversationStatus.escalated),
            )

            await session.flush()
            esc_id = escalation.id

        self._logger.info(
            "escalation_created",
            escalation_id=str(esc_id),
            trigger=trigger.value,
            priority=priority.value,
            tenant=tenant.slug,
        )

        # 4. Redis pub/sub notification
        try:
            redis = get_redis()
            payload = {
                "event": "new_escalation",
                "escalation_id": str(esc_id),
                "conversation_id": str(conversation_id),
                "trigger_type": trigger.value,
                "priority": priority.value,
                "context_summary": context_summary,
                "created_at": datetime.now(UTC).isoformat(),
            }
            await redis.publish(
                f"{tenant.slug}:escalations:new",
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            self._logger.warning(
                "escalation_redis_notify_failed",
                error=str(exc),
                tenant=tenant.slug,
            )

        # 5. Audit log
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=None,
                user_type="system",
                action="create",
                resource_type="escalation",
                resource_id=str(esc_id),
                details={
                    "trigger": trigger.value,
                    "priority": priority.value,
                    "conversation_id": str(conversation_id),
                },
            ),
        )

        # Return a lightweight object with the id
        escalation.id = esc_id
        return escalation

    # ------------------------------------------------------------------
    # Context summary
    # ------------------------------------------------------------------

    async def generate_context_summary(
        self,
        conversation_id: uuid.UUID,
        tenant: TenantContext,
    ) -> str:
        """Generate a conversation summary via Gemini for the human agent.

        Loads the last 10 messages and asks Gemini for a concise ~200 token
        summary including: main topic, questions asked, what failed, and
        user's emotional tone.

        Args:
            conversation_id: Conversation to summarize.
            tenant: Tenant context for DB and Gemini access.

        Returns:
            Summary text string.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Message.direction, Message.content)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.desc())
                .limit(10),
            )
            rows = result.all()

        if not rows:
            return "Aucun message dans la conversation."

        # Build conversation transcript (chronological order)
        transcript_lines = []
        for direction, content in reversed(rows):
            role = "Utilisateur" if direction == MessageDirection.inbound else "Bot"
            transcript_lines.append(f"{role}: {content or '[media]'}")

        transcript = "\n".join(transcript_lines)

        system_prompt = (
            "Tu es un assistant qui r\u00e9sume des conversations WhatsApp "
            "pour un agent CRI (Centre R\u00e9gional d'Investissement). "
            "Produis un r\u00e9sum\u00e9 concis (~200 tokens) incluant :\n"
            "- Sujet principal de la conversation\n"
            "- Questions pos\u00e9es par l'utilisateur\n"
            "- Ce qui n'a pas fonctionn\u00e9 (si applicable)\n"
            "- Ton \u00e9motionnel de l'utilisateur\n"
            "R\u00e9ponds en fran\u00e7ais."
        )

        summary = await self._gemini.generate_simple(
            prompt=f"Conversation \u00e0 r\u00e9sumer :\n\n{transcript}",
            tenant=tenant,
            system_prompt=system_prompt,
        )
        return summary

    # ------------------------------------------------------------------
    # Assign
    # ------------------------------------------------------------------

    async def assign_escalation(
        self,
        escalation_id: uuid.UUID,
        admin_id: uuid.UUID,
        tenant: TenantContext,
    ) -> Escalation:
        """Assign an escalation to a human agent.

        Updates status to 'assigned' and conversation to 'human_handled'.

        Args:
            escalation_id: Escalation to assign.
            admin_id: Admin taking over.
            tenant: Tenant context.

        Returns:
            Updated Escalation record.
        """
        now = datetime.now(UTC)
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Escalation).where(Escalation.id == escalation_id),
            )
            escalation = result.scalar_one()

            escalation.assigned_to = admin_id
            escalation.status = EscalationStatus.assigned
            escalation.assigned_at = now

            await session.execute(
                update(Conversation)
                .where(Conversation.id == escalation.conversation_id)
                .values(status=ConversationStatus.human_handled),
            )

        self._logger.info(
            "escalation_assigned",
            escalation_id=str(escalation_id),
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )

        # Redis notification
        try:
            redis = get_redis()
            payload = {
                "event": "escalation_assigned",
                "escalation_id": str(escalation_id),
                "admin_id": str(admin_id),
                "assigned_at": now.isoformat(),
            }
            await redis.publish(
                f"{tenant.slug}:escalations:assigned",
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            self._logger.warning(
                "escalation_redis_notify_failed",
                error=str(exc),
                tenant=tenant.slug,
            )

        # Audit
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="assign",
                resource_type="escalation",
                resource_id=str(escalation_id),
            ),
        )

        return escalation

    # ------------------------------------------------------------------
    # Respond via WhatsApp
    # ------------------------------------------------------------------

    async def respond_via_whatsapp(
        self,
        escalation_id: uuid.UUID,
        message: str,
        admin_id: uuid.UUID,
        tenant: TenantContext,
    ) -> str:
        """Send a message to the user on behalf of the human agent.

        The message is sent from the tenant's WhatsApp number. A Message
        record is created in the tenant DB.

        Args:
            escalation_id: Escalation being handled.
            message: Text message from the human agent.
            admin_id: Admin sending the message.
            tenant: Tenant context.

        Returns:
            WhatsApp message ID (wamid).
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Escalation).where(Escalation.id == escalation_id),
            )
            escalation = result.scalar_one()

            # Get the phone number via conversation → contact
            conv_result = await session.execute(
                select(Contact.phone)
                .join(Conversation, Conversation.contact_id == Contact.id)
                .where(Conversation.id == escalation.conversation_id),
            )
            phone = conv_result.scalar_one()

            # Send WhatsApp message
            wamid = await self._sender.send_text(tenant, phone, message)

            # Persist outbound message
            msg = Message(
                conversation_id=escalation.conversation_id,
                direction=MessageDirection.outbound,
                type=MessageType.text,
                content=message,
                whatsapp_message_id=wamid,
                timestamp=datetime.now(UTC),
            )
            session.add(msg)

            # Update status to in_progress if currently assigned
            if escalation.status == EscalationStatus.assigned:
                escalation.status = EscalationStatus.in_progress

        self._logger.info(
            "escalation_response_sent",
            escalation_id=str(escalation_id),
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )

        # Audit
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="respond",
                resource_type="escalation",
                resource_id=str(escalation_id),
            ),
        )

        return wamid

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    async def close_escalation(
        self,
        escalation_id: uuid.UUID,
        resolution_notes: str,
        admin_id: uuid.UUID,
        tenant: TenantContext,
        language: str = "fr",
    ) -> Escalation:
        """Close an escalation and return conversation to auto mode.

        Steps:
        1. Update escalation status to resolved
        2. Update conversation.status back to active
        3. Send closure message via WhatsApp
        4. Redis notification
        5. Audit log

        Args:
            escalation_id: Escalation to close.
            resolution_notes: Notes from the human agent.
            admin_id: Admin closing the escalation.
            tenant: Tenant context.
            language: User's language for the closure message.

        Returns:
            Updated Escalation record.
        """
        now = datetime.now(UTC)
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Escalation).where(Escalation.id == escalation_id),
            )
            escalation = result.scalar_one()

            escalation.status = EscalationStatus.resolved
            escalation.resolution_notes = resolution_notes
            escalation.resolved_at = now

            # Return conversation to active (auto mode)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == escalation.conversation_id)
                .values(status=ConversationStatus.active),
            )

            # Get phone for closure message
            conv_result = await session.execute(
                select(Contact.phone)
                .join(Conversation, Conversation.contact_id == Contact.id)
                .where(Conversation.id == escalation.conversation_id),
            )
            phone = conv_result.scalar_one()

        self._logger.info(
            "escalation_closed",
            escalation_id=str(escalation_id),
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )

        # Send closure message
        try:
            closure_msg = CLOSURE_MESSAGES.get(language, CLOSURE_MESSAGES["fr"])
            await self._sender.send_text(tenant, phone, closure_msg)
        except Exception as exc:
            self._logger.warning(
                "closure_message_failed",
                error=str(exc),
                tenant=tenant.slug,
            )

        # Redis notification
        try:
            redis = get_redis()
            payload = {
                "event": "escalation_resolved",
                "escalation_id": str(escalation_id),
                "admin_id": str(admin_id),
                "resolved_at": now.isoformat(),
            }
            await redis.publish(
                f"{tenant.slug}:escalations:resolved",
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            self._logger.warning(
                "escalation_redis_notify_failed",
                error=str(exc),
                tenant=tenant.slug,
            )

        # Audit
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="close",
                resource_type="escalation",
                resource_id=str(escalation_id),
            ),
        )

        return escalation

    # ------------------------------------------------------------------
    # List pending
    # ------------------------------------------------------------------

    async def get_pending_escalations(
        self,
        tenant: TenantContext,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Escalation], int]:
        """List pending/assigned/in_progress escalations for back-office.

        Ordered by priority (high first) then by creation date (oldest first).

        Args:
            tenant: Tenant context.
            page: Page number (1-indexed).
            size: Items per page.

        Returns:
            Tuple of (escalation_list, total_count).
        """
        active_statuses = [
            EscalationStatus.pending,
            EscalationStatus.assigned,
            EscalationStatus.in_progress,
        ]

        priority_order = case(
            (Escalation.priority == EscalationPriority.high, 0),
            (Escalation.priority == EscalationPriority.medium, 1),
            (Escalation.priority == EscalationPriority.low, 2),
            else_=3,
        )

        async with tenant.db_session() as session:
            base = select(Escalation).where(
                Escalation.status.in_(active_statuses),
            )

            # Count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # Paginated data
            offset = (page - 1) * size
            data_result = await session.execute(
                base.order_by(priority_order, Escalation.created_at.asc())
                .offset(offset)
                .limit(size),
            )
            items = list(data_result.scalars().all())

        return items, total


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_escalation_service: EscalationService | None = None


def get_escalation_service() -> EscalationService:
    """Get or create the EscalationService singleton."""
    global _escalation_service  # noqa: PLW0603
    if _escalation_service is None:
        _escalation_service = EscalationService(
            gemini=get_gemini_service(),
            sender=WhatsAppSenderService(),
            audit=get_audit_service(),
        )
    return _escalation_service
