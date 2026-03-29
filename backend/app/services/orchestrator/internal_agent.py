"""InternalAgent — LangGraph node for CRI internal staff queries (Phase 2).

Handles read-only consultation for whitelisted CRI employees:
- Whitelist verification on every invocation (no cache)
- Sub-intent classification (stats / faq / report)
- Dashboard statistics, FAQ search (RAG), report generation

Follows the same pattern as FAQAgent: receives (state, tenant),
returns partial state dict, routes through ResponseValidator →
FeedbackCollector.
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.schemas.audit import AuditLogCreate
from app.services.internal.service import (
    REFUSAL_MESSAGES,
    InternalAgentService,
    get_internal_agent_service,
)
from app.services.orchestrator.state import ConversationState
from app.services.rag.prompts import PromptTemplates

logger = structlog.get_logger()

# Formatting templates for stats display (WhatsApp-friendly)
_STATS_TEMPLATES: dict[str, str] = {
    "fr": (
        "Statistiques du tenant :\n"
        "• Conversations totales : {total_conversations}\n"
        "• Questions en attente : {pending_unanswered}\n"
        "• Contacts enregistrés : {total_contacts}"
    ),
    "ar": (
        "إحصائيات المركز:\n"
        "• المحادثات الإجمالية: {total_conversations}\n"
        "• الأسئلة المعلقة: {pending_unanswered}\n"
        "• جهات الاتصال المسجلة: {total_contacts}"
    ),
    "en": (
        "Tenant statistics:\n"
        "• Total conversations: {total_conversations}\n"
        "• Pending unanswered: {pending_unanswered}\n"
        "• Registered contacts: {total_contacts}"
    ),
}


class InternalAgent:
    """LangGraph node for the CRI internal agent (Phase 2).

    Flow:
    1. Verify whitelist (every call, no cache)
    2. Audit log the access attempt
    3. If not whitelisted → refusal message
    4. Classify sub-intent (stats / faq / report)
    5. Execute read-only query
    6. Return partial state → passes to ResponseValidator

    Args:
        internal_service: Business logic service for internal operations.
    """

    def __init__(self, internal_service: InternalAgentService) -> None:
        self._service = internal_service
        self._logger = logger.bind(service="internal_agent")

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Process an internal agent query.

        Args:
            state: Current conversation state with query and phone.
            tenant: Tenant context for DB, Qdrant, and Gemini access.

        Returns:
            Partial state update with response, is_internal_user,
            agent_type, and optionally chunk_ids/confidence.
        """
        phone = state.get("phone", "")
        query = state.get("query", "")
        language = state.get("language", "fr")
        updates: dict = {"agent_type": "internal"}

        try:
            # Step 1: Whitelist verification (every call)
            is_whitelisted = await self._service.verify_whitelist(tenant, phone)
            updates["is_internal_user"] = is_whitelisted

            # Step 2: Audit log (fire-and-forget)
            await self._service._audit.log_action(
                AuditLogCreate(
                    tenant_slug=tenant.slug,
                    user_id=None,
                    user_type="internal",
                    action="access",
                    resource_type="internal_agent",
                    details={
                        "phone_masked": phone[:6] + "***" if len(phone) > 6 else "***",
                        "is_whitelisted": is_whitelisted,
                    },
                ),
            )

            # Step 3: Reject non-whitelisted users
            if not is_whitelisted:
                updates["response"] = REFUSAL_MESSAGES.get(
                    language, REFUSAL_MESSAGES["fr"],
                )
                self._logger.info(
                    "internal_access_denied",
                    tenant=tenant.slug,
                    phone_masked=phone[:6] + "***" if len(phone) > 6 else "***",
                )
                return updates  # type: ignore[return-value]

            # Step 4: Classify sub-intent
            sub_intent = await self._service.classify_sub_intent(query, tenant)

            self._logger.info(
                "internal_sub_intent",
                sub_intent=sub_intent,
                tenant=tenant.slug,
            )

            # Step 5: Execute by sub-intent
            if sub_intent == "stats":
                stats = await self._service.get_dashboard_stats(tenant)
                template = _STATS_TEMPLATES.get(language, _STATS_TEMPLATES["fr"])
                updates["response"] = template.format(**stats)
                updates["confidence"] = 1.0

            elif sub_intent == "report":
                report = await self._service.generate_report(
                    tenant, query, language,
                )
                updates["response"] = report
                updates["confidence"] = 1.0

            else:  # "faq" — default
                history = [
                    {
                        "role": m.get("role", "user") if isinstance(m, dict) else "user",
                        "content": m.get("content", "") if isinstance(m, dict) else str(m),
                    }
                    for m in state.get("messages", [])[-5:]
                ]
                result = await self._service.search_faq(
                    tenant, query, language, history,
                )
                updates["response"] = result["response"]
                updates["chunk_ids"] = result["chunk_ids"]
                updates["confidence"] = result["confidence"]
                updates["retrieved_chunks"] = result["retrieved_chunks"]

        except Exception as exc:
            self._logger.error(
                "internal_agent_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            updates["error"] = str(exc)
            updates["response"] = PromptTemplates.get_message("no_answer", language)
            updates["confidence"] = 0.0

        return updates  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_internal_agent: InternalAgent | None = None


def get_internal_agent() -> InternalAgent:
    """Get or create the InternalAgent singleton."""
    global _internal_agent  # noqa: PLW0603
    if _internal_agent is None:
        _internal_agent = InternalAgent(
            internal_service=get_internal_agent_service(),
        )
    return _internal_agent
