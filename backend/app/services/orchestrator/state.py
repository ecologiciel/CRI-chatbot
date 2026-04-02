"""LangGraph conversation state and intent type constants.

ConversationState is the shared state flowing through the LangGraph
conversation graph. Each node reads and updates fields relevant to
its step. TenantContext is stored as a serialized dict (not the frozen
dataclass) so it remains JSON-serializable for LangGraph checkpointing.
Node wrappers in graph.py reconstruct TenantContext from this dict.
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
    tenant_context: dict  # serialized TenantContext (id, slug, name, status, whatsapp_config)
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

    # ── Phase 2: Internal agent & escalation ──
    is_internal_user: bool  # True if phone is in the tenant's whitelist
    agent_type: str  # "public" or "internal"
    escalation_id: str | None  # UUID of escalation record if created
    consecutive_low_confidence: int  # consecutive low-confidence RAG responses
    conversation_id: str | None  # DB conversation UUID (passed from handler)

    # ── Phase 3: Dossier tracking ──
    tracking_state: str | None  # TrackingStep: idle, awaiting_identifier, otp_sent, authenticated
    authenticated_phone: str | None  # Phone verified via OTP (for session persistence)


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
