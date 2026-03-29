"""EscalationHandler — LangGraph node for human agent escalation (Phase 2).

Invoked when:
1. IntentDetector classifies intent as "escalade" (explicit request)
2. Auto-detection triggers escalation (RAG failure, sensitive topic, etc.)

Creates the escalation record via EscalationService, sets the transition
message in state["response"], and lets MessageHandler send it via WhatsApp.

Follows the same pattern as InternalAgent: receives (state, tenant),
returns partial state dict, routes directly to END.

Note: EscalationService imports are deferred to avoid circular imports
(this module ← graph ← orchestrator.__init__ ← service.py → state).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.core.tenant import TenantContext
from app.models.enums import EscalationTrigger
from app.services.orchestrator.state import ConversationState, IntentType
from app.services.rag.prompts import PromptTemplates

if TYPE_CHECKING:
    from app.services.escalation.service import EscalationService

logger = structlog.get_logger()


class EscalationHandler:
    """LangGraph node for escalation to a human CRI agent.

    Flow:
    1. Check if already escalated (avoid duplicates)
    2. Determine trigger (explicit intent or auto-detection)
    3. Look up active conversation from phone
    4. Create escalation via EscalationService
    5. Return transition message in state["response"]

    Args:
        escalation_service: Business logic service for escalations.
    """

    def __init__(self, escalation_service: EscalationService) -> None:
        self._service = escalation_service
        self._logger = logger.bind(service="escalation_handler")

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Process an escalation request.

        Args:
            state: Current conversation state with query and phone.
            tenant: Tenant context for DB, Gemini, and Redis access.

        Returns:
            Partial state update with response and escalation_id.
        """
        # Deferred import to avoid circular dependency
        from app.services.escalation.service import (
            ALREADY_ESCALATED_MESSAGES,
            TRANSITION_MESSAGES,
        )

        phone = state.get("phone", "")
        query = state.get("query", "")
        language = state.get("language", "fr")
        intent = state.get("intent", "")

        try:
            # Step 1: Check if already escalated (avoid duplicates)
            if state.get("escalation_id"):
                self._logger.info(
                    "escalation_already_active",
                    tenant=tenant.slug,
                    phone_masked=phone[:6] + "***" if len(phone) > 6 else "***",
                )
                msg = ALREADY_ESCALATED_MESSAGES.get(
                    language, ALREADY_ESCALATED_MESSAGES["fr"],
                )
                return {"response": msg}  # type: ignore[return-value]

            # Step 2: Determine trigger
            if intent == IntentType.ESCALADE:
                trigger = EscalationTrigger.explicit_request
            else:
                detected = await self._service.detect_escalation(state)
                if detected:
                    trigger = detected
                else:
                    # No trigger detected — shouldn't happen but safety fallback
                    self._logger.warning(
                        "escalation_no_trigger",
                        intent=intent,
                        tenant=tenant.slug,
                    )
                    return {  # type: ignore[return-value]
                        "response": PromptTemplates.get_message("no_answer", language),
                    }

            # Step 3: Look up active conversation (prefer state, fallback to DB)
            conversation_id_str = state.get("conversation_id")
            if conversation_id_str:
                import uuid as _uuid

                conversation_id = _uuid.UUID(conversation_id_str)
            else:
                conversation_id = await self._service.lookup_active_conversation(
                    tenant, phone,
                )
            if conversation_id is None:
                self._logger.error(
                    "escalation_no_active_conversation",
                    tenant=tenant.slug,
                    phone_masked=phone[:6] + "***" if len(phone) > 6 else "***",
                )
                return {  # type: ignore[return-value]
                    "error": "No active conversation found for escalation",
                    "response": PromptTemplates.get_message("no_answer", language),
                }

            # Step 4: Create escalation
            escalation = await self._service.create_escalation(
                conversation_id=conversation_id,
                trigger=trigger,
                user_message=query,
                tenant=tenant,
            )

            self._logger.info(
                "escalation_created_by_handler",
                escalation_id=str(escalation.id),
                trigger=trigger.value,
                tenant=tenant.slug,
            )

            # Step 5: Return transition message
            msg = TRANSITION_MESSAGES.get(language, TRANSITION_MESSAGES["fr"])
            return {  # type: ignore[return-value]
                "escalation_id": str(escalation.id),
                "response": msg,
            }

        except Exception as exc:
            self._logger.error(
                "escalation_handler_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            return {  # type: ignore[return-value]
                "error": str(exc),
                "response": PromptTemplates.get_message("no_answer", language),
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_escalation_handler: EscalationHandler | None = None


def get_escalation_handler() -> EscalationHandler:
    """Get or create the EscalationHandler singleton."""
    global _escalation_handler  # noqa: PLW0603
    if _escalation_handler is None:
        # Deferred import to avoid circular dependency
        from app.services.escalation.service import get_escalation_service

        _escalation_handler = EscalationHandler(
            escalation_service=get_escalation_service(),
        )
    return _escalation_handler
