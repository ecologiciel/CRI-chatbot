"""FeedbackCollector — LangGraph node for post-response feedback buttons.

Sends WhatsApp interactive buttons (thumbs up / thumbs down / talk to agent)
after FAQ responses only. Non-critical: failures are logged but never
propagate to the conversation flow.
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.services.orchestrator.state import ConversationState, IntentType
from app.services.rag.prompts import PromptTemplates
from app.services.whatsapp.sender import WhatsAppSenderService

logger = structlog.get_logger()

# WhatsApp button title limit is 20 chars (incl. emoji ~2 chars each)
FEEDBACK_BUTTONS: dict[str, list[dict[str, str]]] = {
    "fr": [
        {"id": "feedback_positive", "title": "Utile"},
        {"id": "feedback_negative", "title": "Pas utile"},
        {"id": "feedback_unclear", "title": "Parler a un agent"},
    ],
    "ar": [
        {"id": "feedback_positive", "title": "مفيد"},
        {"id": "feedback_negative", "title": "غير مفيد"},
        {"id": "feedback_unclear", "title": "التحدث مع موظف"},
    ],
    "en": [
        {"id": "feedback_positive", "title": "Helpful"},
        {"id": "feedback_negative", "title": "Not helpful"},
        {"id": "feedback_unclear", "title": "Talk to agent"},
    ],
}

# Intents that should trigger feedback buttons
_FEEDBACK_INTENTS: set[str] = {IntentType.FAQ, IntentType.INTERNE}


class FeedbackCollector:
    """LangGraph node: send feedback buttons after FAQ responses.

    Only triggers for FAQ intent — greetings, out_of_scope, etc. are skipped.
    Feedback button clicks are processed in a separate webhook flow (Wave 8+).
    """

    def __init__(self, sender: WhatsAppSenderService) -> None:
        self._sender = sender
        self._logger = logger.bind(service="feedback_collector")

    async def collect(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Send feedback buttons after the response.

        Args:
            state: Current conversation state with intent and phone.
            tenant: Tenant context for WhatsApp API.

        Returns:
            Empty partial state (feedback doesn't modify conversation state).
        """
        intent = state.get("intent", "")
        if intent not in _FEEDBACK_INTENTS:
            return {}  # type: ignore[return-value]

        phone = state.get("phone", "")
        if not phone:
            return {}  # type: ignore[return-value]

        language = state.get("language", "fr")

        try:
            buttons = FEEDBACK_BUTTONS.get(language, FEEDBACK_BUTTONS["fr"])
            body_text = PromptTemplates.get_message("feedback_request", language)

            await self._sender.send_buttons(tenant, phone, body_text, buttons)

            self._logger.info(
                "feedback_requested",
                tenant=tenant.slug,
                intent=intent,
                language=language,
            )
        except Exception as exc:
            # Feedback is non-critical — log but never fail the flow
            self._logger.warning(
                "feedback_send_failed",
                error=str(exc),
                tenant=tenant.slug,
            )

        return {}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_feedback_collector: FeedbackCollector | None = None


def get_feedback_collector() -> FeedbackCollector:
    """Get or create the FeedbackCollector singleton."""
    global _feedback_collector  # noqa: PLW0603
    if _feedback_collector is None:
        _feedback_collector = FeedbackCollector(
            sender=WhatsAppSenderService(),
        )
    return _feedback_collector
