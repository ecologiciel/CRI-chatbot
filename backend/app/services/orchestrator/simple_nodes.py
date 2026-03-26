"""Simple LangGraph nodes — no external I/O, no tenant required.

These nodes return canned responses for intents that don't need RAG,
Gemini, or any external service. They read language from state and
set the response field.

Placeholder nodes (Phase 2/3) return trilingual "coming soon" messages
so users aren't left without guidance.
"""

from __future__ import annotations

from app.services.orchestrator.state import ConversationState
from app.services.rag.prompts import PromptTemplates


class GreetingNode:
    """Return a greeting message via PromptTemplates."""

    async def handle(self, state: ConversationState) -> ConversationState:
        language = state.get("language", "fr")
        return {"response": PromptTemplates.get_message("greeting", language)}  # type: ignore[return-value]


class OutOfScopeNode:
    """Return an out-of-scope message via PromptTemplates."""

    async def handle(self, state: ConversationState) -> ConversationState:
        language = state.get("language", "fr")
        return {"response": PromptTemplates.get_message("out_of_scope", language)}  # type: ignore[return-value]


class BlockedResponseNode:
    """Return the guard rejection message (or a fallback)."""

    async def handle(self, state: ConversationState) -> ConversationState:
        guard_msg = state.get("guard_message")
        if guard_msg:
            return {"response": guard_msg}  # type: ignore[return-value]
        language = state.get("language", "fr")
        return {"response": PromptTemplates.get_message("out_of_scope", language)}  # type: ignore[return-value]


class TrackingPlaceholder:
    """Phase 3 placeholder for dossier tracking."""

    MESSAGES: dict[str, str] = {
        "fr": (
            "Le suivi de dossier sera disponible prochainement. "
            "Pour consulter votre dossier, veuillez contacter le CRI "
            "au 05 37 77 64 00."
        ),
        "ar": (
            "\u0633\u062a\u0643\u0648\u0646 \u062e\u062f\u0645\u0629 "
            "\u062a\u062a\u0628\u0639 \u0627\u0644\u0645\u0644\u0641\u0627\u062a "
            "\u0645\u062a\u0627\u062d\u0629 \u0642\u0631\u064a\u0628\u0627\u064b. "
            "\u0644\u0644\u0627\u0637\u0644\u0627\u0639 \u0639\u0644\u0649 "
            "\u0645\u0644\u0641\u0643\u0645\u060c \u064a\u0631\u062c\u0649 "
            "\u0627\u0644\u0627\u062a\u0635\u0627\u0644 \u0628\u0627\u0644\u0645\u0631\u0643\u0632 "
            "\u0627\u0644\u062c\u0647\u0648\u064a \u0644\u0644\u0627\u0633\u062a\u062b\u0645\u0627\u0631."
        ),
        "en": (
            "Dossier tracking will be available soon. "
            "To check your dossier, please contact the CRI "
            "at 05 37 77 64 00."
        ),
    }

    async def handle(self, state: ConversationState) -> ConversationState:
        lang = state.get("language", "fr")
        return {"response": self.MESSAGES.get(lang, self.MESSAGES["fr"])}  # type: ignore[return-value]


class EscalationPlaceholder:
    """Phase 2 placeholder for human escalation."""

    MESSAGES: dict[str, str] = {
        "fr": (
            "Je vous mets en relation avec un conseiller CRI. "
            "Veuillez patienter ou contacter le 05 37 77 64 00."
        ),
        "ar": (
            "\u0633\u0623\u0642\u0648\u0645 \u0628\u062a\u062d\u0648\u064a\u0644\u0643\u0645 "
            "\u0625\u0644\u0649 \u0645\u0633\u062a\u0634\u0627\u0631 \u0627\u0644\u0645\u0631\u0643\u0632. "
            "\u064a\u0631\u062c\u0649 \u0627\u0644\u0627\u0646\u062a\u0638\u0627\u0631 "
            "\u0623\u0648 \u0627\u0644\u0627\u062a\u0635\u0627\u0644 \u0628\u0627\u0644\u0631\u0642\u0645 "
            "05 37 77 64 00."
        ),
        "en": (
            "I'm connecting you with a CRI advisor. "
            "Please wait or contact 05 37 77 64 00."
        ),
    }

    async def handle(self, state: ConversationState) -> ConversationState:
        lang = state.get("language", "fr")
        return {"response": self.MESSAGES.get(lang, self.MESSAGES["fr"])}  # type: ignore[return-value]


class InternalPlaceholder:
    """Phase 2 placeholder for internal agent."""

    MESSAGES: dict[str, str] = {
        "fr": "L'agent interne CRI sera disponible prochainement.",
        "ar": (
            "\u0633\u064a\u0643\u0648\u0646 \u0627\u0644\u0648\u0643\u064a\u0644 "
            "\u0627\u0644\u062f\u0627\u062e\u0644\u064a \u0644\u0644\u0645\u0631\u0643\u0632 "
            "\u0645\u062a\u0627\u062d\u0627\u064b \u0642\u0631\u064a\u0628\u0627\u064b."
        ),
        "en": "The internal CRI agent will be available soon.",
    }

    async def handle(self, state: ConversationState) -> ConversationState:
        lang = state.get("language", "fr")
        return {"response": self.MESSAGES.get(lang, self.MESSAGES["fr"])}  # type: ignore[return-value]
