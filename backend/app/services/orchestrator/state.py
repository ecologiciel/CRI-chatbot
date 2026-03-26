"""LangGraph conversation state and intent type constants.

ConversationState is the shared state flowing through the LangGraph
conversation graph. Each node reads and updates fields relevant to
its step. TenantContext is NOT stored in state (not JSON-serializable
for LangGraph checkpointing) — it is passed as a separate parameter.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ConversationState(TypedDict, total=False):
    """Shared state for the LangGraph conversation graph.

    Fields use total=False so nodes can return partial updates
    (LangGraph merges returned dicts into the current state).
    """

    # ── Tenant & user identity ──
    tenant_slug: str
    phone: str  # user's WhatsApp phone (E.164)

    # ── Language & intent detection ──
    language: str  # detected language: "fr", "ar", "en"
    intent: str  # detected intent (see IntentType)

    # ── Current query ──
    query: str  # raw user message text
    messages: Annotated[list, add_messages]  # conversation history (append-only)

    # ── RAG pipeline ──
    retrieved_chunks: list[dict]  # chunks from Qdrant retrieval
    response: str  # generated response text
    chunk_ids: list[str]  # chunk IDs for feedback correlation
    confidence: float  # retrieval confidence score

    # ── Guardrails ──
    is_safe: bool  # input guard result
    guard_message: str | None  # rejection message if blocked

    # ── Incentives navigation ──
    incentive_state: dict
    # Structure: {
    #   "current_category_id": str | None,
    #   "navigation_path": list[str],  # breadcrumb of category IDs
    #   "selected_item_id": str | None,
    # }

    # ── Error handling ──
    error: str | None


class IntentType:
    """Intent classification constants.

    Used by IntentDetector (output) and Router (input)
    to determine which agent handles the conversation.
    """

    FAQ = "faq"
    INCITATIONS = "incitations"
    SUIVI_DOSSIER = "suivi_dossier"
    INTERNE = "interne"
    ESCALADE = "escalade"
    HORS_PERIMETRE = "hors_perimetre"
    SALUTATION = "salutation"

    ALL: list[str] = [
        FAQ,
        INCITATIONS,
        SUIVI_DOSSIER,
        INTERNE,
        ESCALADE,
        HORS_PERIMETRE,
        SALUTATION,
    ]
