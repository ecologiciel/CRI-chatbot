"""Intent detection LangGraph node.

Two-step approach:
1. Input guardrails (regex — instant, zero LLM cost)
2. Gemini classification (~50 tokens — fast and cheap)

Blocked messages skip Gemini entirely (cost saving + security).
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.services.ai.gemini import GeminiService, get_gemini_service
from app.services.ai.language import LanguageDetectionService, get_language_service
from app.services.guardrails.input_guard import (
    InputGuardService,
    get_input_guard_service,
)
from app.services.orchestrator.state import ConversationState, IntentType

logger = structlog.get_logger()


class IntentDetector:
    """Detect user intent from message text.

    Uses a 2-step approach:
    1. Input guardrails (regex check — instant, no LLM cost)
    2. Gemini classification (~50 tokens — fast and cheap)
    """

    def __init__(
        self,
        gemini: GeminiService,
        language_service: LanguageDetectionService,
        input_guard: InputGuardService,
    ) -> None:
        self._gemini = gemini
        self._language = language_service
        self._guard = input_guard
        self._logger = logger.bind(service="intent_detector")

    async def detect(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """LangGraph node: detect intent and language.

        Steps:
        1. Detect language
        2. Run input guardrails
        3. If blocked → set is_safe=False, guard_message, intent=hors_perimetre
        4. If safe → classify intent via Gemini
        5. Update and return state with language, intent, is_safe

        Args:
            state: Current conversation state.
            tenant: Tenant context (for Gemini billing and DB access).

        Returns:
            Updated conversation state with language, intent, and guard fields.
        """
        query = state.get("query", "")
        updates: dict = {}

        # Step 1: Detect language
        lang_result = await self._language.detect(query, tenant)
        updates["language"] = lang_result.language.value

        # Step 2: Input guardrails
        guard_result = await self._guard.check(
            query,
            tenant=tenant,
            language=lang_result.language.value,
        )

        if not guard_result.is_safe:
            updates["is_safe"] = False
            updates["guard_message"] = guard_result.reason
            updates["intent"] = IntentType.HORS_PERIMETRE
            self._logger.warning(
                "intent_blocked_by_guard",
                category=guard_result.category,
                tenant=tenant.slug,
            )
            return updates  # type: ignore[return-value]

        updates["is_safe"] = True
        updates["guard_message"] = None

        # Step 3: Classify intent via Gemini (~50 tokens)
        intent_raw = await self._gemini.classify_intent(query, tenant)
        intent = intent_raw.strip().lower()

        # Validate against known intents, fallback to FAQ
        if intent not in IntentType.ALL:
            self._logger.info(
                "intent_unknown_fallback",
                raw_intent=intent,
                fallback=IntentType.FAQ,
                tenant=tenant.slug,
            )
            intent = IntentType.FAQ

        updates["intent"] = intent

        self._logger.info(
            "intent_detected",
            intent=intent,
            language=lang_result.language.value,
            method=lang_result.method,
            tenant=tenant.slug,
        )

        return updates  # type: ignore[return-value]


# ── Singleton ──

_intent_detector: IntentDetector | None = None


def get_intent_detector() -> IntentDetector:
    """Get or create the IntentDetector singleton."""
    global _intent_detector  # noqa: PLW0603
    if _intent_detector is None:
        _intent_detector = IntentDetector(
            gemini=get_gemini_service(),
            language_service=get_language_service(),
            input_guard=get_input_guard_service(),
        )
    return _intent_detector
