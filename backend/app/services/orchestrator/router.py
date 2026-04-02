"""Conditional router for the LangGraph conversation graph.

Pure function — no I/O, no async, no dependencies.
Maps detected intent to the next node name in the graph.
"""

from __future__ import annotations

from app.services.orchestrator.state import ConversationState, IntentType


class Router:
    """LangGraph conditional routing based on detected intent.

    Used as a conditional edge function in the LangGraph graph.
    Returns a string identifying the next node to execute.
    """

    # Intent → node name mapping
    _ROUTING_MAP: dict[str, str] = {
        IntentType.SALUTATION: "greeting_response",
        IntentType.FAQ: "faq_agent",
        IntentType.INCITATIONS: "incentives_agent",
        IntentType.SUIVI_DOSSIER: "tracking_agent",
        IntentType.ESCALADE: "escalation_handler",
        IntentType.INTERNE: "internal_agent",
        IntentType.HORS_PERIMETRE: "out_of_scope_response",
    }

    @staticmethod
    def route(state: ConversationState) -> str:
        """Return the next node name based on intent and safety.

        Priority:
        1. is_safe=False → "blocked_response" (guardrails override)
        2. Intent lookup in routing map
        3. Fallback → "faq_agent"

        Args:
            state: Current conversation state (must have intent and is_safe).

        Returns:
            Node name string for LangGraph conditional edge.
        """
        if not state.get("is_safe", True):
            return "blocked_response"

        intent = state.get("intent", IntentType.FAQ)
        return Router._ROUTING_MAP.get(intent, "faq_agent")
