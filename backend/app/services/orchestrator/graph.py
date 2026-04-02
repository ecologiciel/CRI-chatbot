"""Complete LangGraph conversation graph — v3 (Wave 8 + 15 + 17 + 25).

Assembles all nodes into a compiled StateGraph:

    intent_detector ─(Router)──> faq_agent ──(auto-escalation?)──> escalation_handler ──> END
                               │                    └──────────> response_validator ─┐
                               > incentives_agent ──────────────> response_validator ─┤
                               > internal_agent ────────────────> response_validator ─┤
                               > tracking_agent ────────────────> response_validator ─┘
                               │                                        ↓
                               │                                feedback_collector ──(feedback-escalation?)──> escalation_handler ──> END
                               │                                        └────────────────────────────────────> END
                               > greeting_response ──────> END
                               > out_of_scope_response ──> END
                               > blocked_response ───────> END
                               > escalation_handler ──────> END

Wave 17: auto/feedback escalation, conversation_id threading.
Wave 25: tracking_placeholder → tracking_agent (OTP-authenticated dossier tracking).

Entry point: ``run_conversation()`` — called from the WhatsApp webhook handler.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from app.core.tenant import TenantContext
from app.services.orchestrator.escalation_handler import get_escalation_handler
from app.services.orchestrator.faq_agent import get_faq_agent
from app.services.orchestrator.feedback_collector import get_feedback_collector
from app.services.orchestrator.incentives_agent import get_incentives_agent
from app.services.orchestrator.intent import get_intent_detector
from app.services.orchestrator.internal_agent import get_internal_agent
from app.services.orchestrator.response_validator import get_response_validator
from app.services.orchestrator.router import Router
from app.services.orchestrator.simple_nodes import (
    BlockedResponseNode,
    GreetingNode,
    OutOfScopeNode,
)
from app.services.orchestrator.tracking_agent import get_tracking_agent
from app.services.orchestrator.state import ConversationState
from app.services.rag.prompts import PromptTemplates

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tenant reconstruction helper
# ---------------------------------------------------------------------------


def _reconstruct_tenant(state: ConversationState) -> TenantContext:
    """Reconstruct a TenantContext from the serialized dict in state."""
    tc = state.get("tenant_context", {})
    return TenantContext(
        id=uuid.UUID(tc["id"]),
        slug=tc["slug"],
        name=tc["name"],
        status=tc["status"],
        whatsapp_config=tc.get("whatsapp_config"),
    )


def _serialize_tenant(tenant: TenantContext) -> dict:
    """Serialize a TenantContext to a JSON-safe dict for state storage."""
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": tenant.name,
        "status": tenant.status,
        "whatsapp_config": tenant.whatsapp_config,
    }


# ---------------------------------------------------------------------------
# Node wrappers
# ---------------------------------------------------------------------------


def _wrap_tenant_node(
    method: Callable[..., Awaitable[ConversationState]],
    node_name: str,
) -> Callable[[ConversationState], Awaitable[ConversationState]]:
    """Wrap a node method that requires (state, tenant) for LangGraph.

    LangGraph calls nodes with just (state). This wrapper reconstructs
    TenantContext from state["tenant_context"] and calls the real method.
    On failure, returns a graceful error response.
    """

    async def wrapper(state: ConversationState) -> ConversationState:
        try:
            tenant = _reconstruct_tenant(state)
            return await method(state, tenant)
        except Exception as exc:
            logger.error(
                "node_error",
                node=node_name,
                error=str(exc),
                tenant=state.get("tenant_slug"),
            )
            language = state.get("language", "fr")
            return {  # type: ignore[return-value]
                "error": f"{node_name}: {exc}",
                "response": PromptTemplates.get_message("no_answer", language),
            }

    wrapper.__name__ = node_name
    return wrapper


def _wrap_simple_node(
    method: Callable[..., Awaitable[ConversationState]],
    node_name: str,
) -> Callable[[ConversationState], Awaitable[ConversationState]]:
    """Wrap a simple node method (no tenant) for LangGraph."""

    async def wrapper(state: ConversationState) -> ConversationState:
        try:
            return await method(state)
        except Exception as exc:
            logger.error(
                "node_error",
                node=node_name,
                error=str(exc),
                tenant=state.get("tenant_slug"),
            )
            language = state.get("language", "fr")
            return {  # type: ignore[return-value]
                "error": f"{node_name}: {exc}",
                "response": PromptTemplates.get_message("no_answer", language),
            }

    wrapper.__name__ = node_name
    return wrapper


# ---------------------------------------------------------------------------
# Conditional-edge routing functions (pure, read-only)
# ---------------------------------------------------------------------------


def check_auto_escalation(state: ConversationState) -> str:
    """Route faq_agent output: escalate on consecutive low confidence.

    FAQAgent already incremented ``consecutive_low_confidence`` in its
    return dict.  LangGraph merges that into state before calling this
    function, so it reads the up-to-date value.

    Returns:
        ``"escalation_handler"`` if consecutive failures >= 2,
        otherwise ``"response_validator"``.
    """
    consecutive = state.get("consecutive_low_confidence", 0)
    if consecutive >= 2:
        return "escalation_handler"
    return "response_validator"


def check_feedback_escalation(state: ConversationState) -> str:
    """Route feedback_collector output: escalate on agent-request keywords.

    Safety net for when IntentDetector misclassifies an escalation
    request as FAQ.  Only triggers when the query contains escalation
    keywords AND the RAG confidence is low (< 0.5).

    Returns:
        ``"escalation_handler"`` or the LangGraph ``END`` sentinel.
    """
    query = (state.get("query") or "").lower()
    escalation_keywords = [
        # Français
        "parler",
        "agent",
        "humain",
        "conseiller",
        # English
        "talk",
        "human",
        "advisor",
        # Arabe
        "\u0645\u0648\u0638\u0641",  # موظف
        "\u0645\u0633\u062a\u0634\u0627\u0631",  # مستشار
        "\u0627\u0644\u062a\u062d\u062f\u062b",  # التحدث
    ]
    if any(kw in query for kw in escalation_keywords) and state.get("confidence", 1.0) < 0.5:
        return "escalation_handler"
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_conversation_graph() -> Any:
    """Build and compile the complete conversation StateGraph.

    Returns:
        Compiled LangGraph graph ready for ``ainvoke()``.
    """
    # Get singleton instances
    intent_detector = get_intent_detector()
    faq_agent = get_faq_agent()
    incentives_agent = get_incentives_agent()
    response_validator = get_response_validator()
    feedback_collector = get_feedback_collector()

    internal_agent = get_internal_agent()
    escalation_handler = get_escalation_handler()
    tracking_agent = get_tracking_agent()

    # Simple nodes (no tenant needed)
    greeting_node = GreetingNode()
    out_of_scope_node = OutOfScopeNode()
    blocked_node = BlockedResponseNode()

    # Build graph
    graph = StateGraph(ConversationState)

    # ── Add nodes (wrapped for LangGraph) ──
    graph.add_node(
        "intent_detector",
        _wrap_tenant_node(intent_detector.detect, "intent_detector"),
    )
    graph.add_node(
        "faq_agent",
        _wrap_tenant_node(faq_agent.handle, "faq_agent"),
    )
    graph.add_node(
        "incentives_agent",
        _wrap_tenant_node(incentives_agent.handle, "incentives_agent"),
    )
    graph.add_node(
        "response_validator",
        _wrap_tenant_node(response_validator.validate, "response_validator"),
    )
    graph.add_node(
        "feedback_collector",
        _wrap_tenant_node(feedback_collector.collect, "feedback_collector"),
    )
    graph.add_node(
        "greeting_response",
        _wrap_simple_node(greeting_node.handle, "greeting_response"),
    )
    graph.add_node(
        "out_of_scope_response",
        _wrap_simple_node(out_of_scope_node.handle, "out_of_scope_response"),
    )
    graph.add_node(
        "blocked_response",
        _wrap_simple_node(blocked_node.handle, "blocked_response"),
    )
    graph.add_node(
        "tracking_agent",
        _wrap_tenant_node(tracking_agent.handle, "tracking_agent"),
    )
    graph.add_node(
        "escalation_handler",
        _wrap_tenant_node(escalation_handler.handle, "escalation_handler"),
    )
    graph.add_node(
        "internal_agent",
        _wrap_tenant_node(internal_agent.handle, "internal_agent"),
    )

    # ── Entry point ──
    graph.set_entry_point("intent_detector")

    # ── Conditional routing after intent detection ──
    graph.add_conditional_edges(
        "intent_detector",
        Router.route,
        {
            "faq_agent": "faq_agent",
            "incentives_agent": "incentives_agent",
            "greeting_response": "greeting_response",
            "out_of_scope_response": "out_of_scope_response",
            "blocked_response": "blocked_response",
            "tracking_agent": "tracking_agent",
            "escalation_handler": "escalation_handler",
            "internal_agent": "internal_agent",
        },
    )

    # ── FAQ → conditional auto-escalation check ──
    graph.add_conditional_edges(
        "faq_agent",
        check_auto_escalation,
        {
            "escalation_handler": "escalation_handler",
            "response_validator": "response_validator",
        },
    )

    # ── Incentives, Internal & Tracking → response_validator (no auto-escalation) ──
    graph.add_edge("incentives_agent", "response_validator")
    graph.add_edge("internal_agent", "response_validator")
    graph.add_edge("tracking_agent", "response_validator")
    graph.add_edge("response_validator", "feedback_collector")

    # ── Feedback → conditional feedback-escalation check ──
    graph.add_conditional_edges(
        "feedback_collector",
        check_feedback_escalation,
        {
            "escalation_handler": "escalation_handler",
            END: END,
        },
    )

    # ── Simple nodes → END ──
    graph.add_edge("greeting_response", END)
    graph.add_edge("out_of_scope_response", END)
    graph.add_edge("blocked_response", END)
    graph.add_edge("escalation_handler", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_conversation_graph: Any | None = None


def get_conversation_graph() -> Any:
    """Get or create the compiled conversation graph singleton."""
    global _conversation_graph  # noqa: PLW0603
    if _conversation_graph is None:
        _conversation_graph = build_conversation_graph()
    return _conversation_graph


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_conversation(
    tenant: TenantContext,
    phone: str,
    query: str,
    conversation_history: list[dict] | None = None,
    incentive_state: dict | None = None,
    conversation_id: str | None = None,
    tracking_state: str | None = None,
) -> dict:
    """Run a user message through the conversation graph.

    Called from the WhatsApp webhook handler. Manages state
    serialization in and result extraction out.

    Args:
        tenant: TenantContext for the current tenant.
        phone: User's WhatsApp phone number (E.164).
        query: User's message text (or button reply ID).
        conversation_history: Previous messages [{role, content}].
        incentive_state: Current position in incentives tree (if any).

    Returns:
        dict with: response, intent, language, chunk_ids, confidence,
        incentive_state, error.
    """
    initial_state: ConversationState = {  # type: ignore[typeddict-item]
        "tenant_slug": tenant.slug,
        "tenant_context": _serialize_tenant(tenant),
        "phone": phone,
        "language": "fr",
        "intent": "",
        "messages": conversation_history or [],
        "query": query,
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": incentive_state or {},
        "error": None,
        "is_internal_user": False,
        "agent_type": "public",
        "escalation_id": None,
        "consecutive_low_confidence": 0,
        "conversation_id": conversation_id,
        "tracking_state": tracking_state,
        "authenticated_phone": None,
    }

    try:
        graph = get_conversation_graph()
        final_state = await graph.ainvoke(initial_state)

        logger.info(
            "conversation_completed",
            tenant=tenant.slug,
            intent=final_state.get("intent"),
            language=final_state.get("language"),
            confidence=final_state.get("confidence"),
            has_error=bool(final_state.get("error")),
        )

        return {
            "response": final_state.get("response", ""),
            "intent": final_state.get("intent", ""),
            "language": final_state.get("language", "fr"),
            "chunk_ids": final_state.get("chunk_ids", []),
            "confidence": final_state.get("confidence", 0.0),
            "incentive_state": final_state.get("incentive_state", {}),
            "agent_type": final_state.get("agent_type", "public"),
            "tracking_state": final_state.get("tracking_state"),
            "error": final_state.get("error"),
        }

    except Exception as exc:
        logger.error(
            "conversation_graph_error",
            error=str(exc),
            tenant=tenant.slug,
            phone=phone[:6] + "***",
        )
        return {
            "response": PromptTemplates.get_message("no_answer", "fr"),
            "intent": "error",
            "language": "fr",
            "chunk_ids": [],
            "confidence": 0.0,
            "incentive_state": incentive_state or {},
            "error": str(exc),
        }
