"""ResponseValidator — LangGraph node for output guardrails.

Delegates to OutputGuardService which handles PII masking,
confidence-based disclaimers, and tone checks. This node is a thin
wrapper that reads from / writes to the ConversationState.
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.services.guardrails.output_guard import (
    OutputGuardService,
    get_output_guard_service,
)
from app.services.orchestrator.state import ConversationState

logger = structlog.get_logger()


class ResponseValidator:
    """LangGraph node: validate and clean the generated response.

    Applies output guardrails (PII masking, confidence disclaimer,
    tone check) before the response is sent to the user.
    """

    def __init__(self, output_guard: OutputGuardService) -> None:
        self._guard = output_guard
        self._logger = logger.bind(service="response_validator")

    async def validate(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Apply output guardrails to the response.

        Args:
            state: Current conversation state with response to validate.
            tenant: Tenant context (used for logging).

        Returns:
            Partial state update with cleaned response.
        """
        response = state.get("response", "")
        if not response:
            return {}  # type: ignore[return-value]

        confidence = state.get("confidence", 1.0)
        language = state.get("language", "fr")

        guard_result = await self._guard.check(response, confidence, language)

        updates: dict = {"response": guard_result.cleaned_text}

        if guard_result.issues:
            self._logger.warning(
                "output_guard_issues",
                issues=guard_result.issues,
                pii_masked=guard_result.pii_masked_count,
                tenant=state.get("tenant_slug"),
            )

        return updates  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_response_validator: ResponseValidator | None = None


def get_response_validator() -> ResponseValidator:
    """Get or create the ResponseValidator singleton."""
    global _response_validator  # noqa: PLW0603
    if _response_validator is None:
        _response_validator = ResponseValidator(
            output_guard=get_output_guard_service(),
        )
    return _response_validator
