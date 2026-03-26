"""IncentivesAgent — LangGraph node for incentives navigation.

Thin delegation wrapper around IncentivesService.handle().
The service owns all business logic (tree navigation, WhatsApp messaging,
state updates); this agent adds defense-in-depth error handling and
structured logging consistent with the other orchestrator nodes.
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.services.incitations.service import IncentivesService, get_incentives_service
from app.services.orchestrator.state import ConversationState

logger = structlog.get_logger()

# Fallback messages when an unexpected error escapes the service layer.
_FALLBACK: dict[str, str] = {
    "fr": "Une erreur est survenue. Veuillez réessayer.",
    "ar": "حدث خطأ. يرجى المحاولة مرة أخرى.",
    "en": "An error occurred. Please try again.",
}


class IncentivesAgent:
    """LangGraph node: handle incentives navigation via WhatsApp interactive messages.

    Delegates entirely to IncentivesService.handle() which:
    - Reads incentive_state from the conversation state
    - Navigates the category tree (root → children → items → detail)
    - Sends WhatsApp buttons / lists / text
    - Returns partial state updates with response and incentive_state
    """

    def __init__(self, incentives: IncentivesService) -> None:
        self._incentives = incentives
        self._logger = logger.bind(service="incentives_agent")

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Process incentives intent by delegating to IncentivesService.

        Args:
            state: Current conversation state with incentive_state and query.
            tenant: Tenant context for DB access and WhatsApp credentials.

        Returns:
            Partial state update with response, incentive_state, and error.
        """
        try:
            result = await self._incentives.handle(state, tenant)
            self._logger.info(
                "incentives_response_generated",
                tenant=tenant.slug,
            )
            return result

        except Exception as exc:
            self._logger.error(
                "incentives_agent_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            language = state.get("language", "fr")
            fallback = _FALLBACK.get(language, _FALLBACK["fr"])
            return {"response": fallback, "error": str(exc)}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_incentives_agent: IncentivesAgent | None = None


def get_incentives_agent() -> IncentivesAgent:
    """Get or create the IncentivesAgent singleton."""
    global _incentives_agent  # noqa: PLW0603
    if _incentives_agent is None:
        _incentives_agent = IncentivesAgent(
            incentives=get_incentives_service(),
        )
    return _incentives_agent
