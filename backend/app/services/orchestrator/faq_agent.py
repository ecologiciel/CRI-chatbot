"""FAQAgent — LangGraph node for FAQ queries via the full RAG pipeline.

Pipeline: retrieve chunks (Qdrant) → generate answer (Gemini) → update state.
Pre-retrieved chunks are passed to GenerationService to avoid double retrieval.
"""

from __future__ import annotations

import uuid

import structlog

from app.core.tenant import TenantContext
from app.schemas.rag import GenerationRequest
from app.services.conversation.service import get_conversation_service
from app.services.guardrails.pii_masker import get_pii_masker
from app.services.orchestrator.state import ConversationState
from app.services.rag.generation import GenerationService, get_generation_service
from app.services.rag.prompts import PromptTemplates
from app.services.rag.retrieval import RetrievalService, get_retrieval_service

logger = structlog.get_logger()

# Matches EscalationService.LOW_CONFIDENCE_THRESHOLD — kept local to avoid
# circular imports (graph → escalation → … → graph).
_LOW_CONFIDENCE_THRESHOLD = 0.5


class FAQOutcomePersistenceError(RuntimeError):
    """The response outcome could not be durably recorded."""


class FAQAgent:
    """LangGraph node: handle FAQ queries via the RAG pipeline.

    Steps:
    1. Retrieve relevant chunks from Qdrant
    2. If no chunks found → return "no_answer" message
    3. Pass query + chunks to GenerationService
    4. Return partial state with response, chunk_ids, confidence
    """

    def __init__(
        self,
        retrieval: RetrievalService,
        generation: GenerationService,
    ) -> None:
        self._retrieval = retrieval
        self._generation = generation
        self._logger = logger.bind(service="faq_agent")

    async def _record_outcome(
        self, state: ConversationState, tenant: TenantContext, updates: dict, *, low: bool
    ) -> None:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            # Offline graph evaluation without a persisted conversation.
            updates["consecutive_low_confidence"] = (
                state.get("consecutive_low_confidence", 0) + 1 if low else 0
            )
            return
        try:
            count = await get_conversation_service().record_faq_outcome(
                tenant, uuid.UUID(str(conversation_id)), low_confidence=low
            )
        except Exception as exc:
            # A commit may have succeeded even if the connection failed. Never
            # retry this counter update in the provider error handler.
            raise FAQOutcomePersistenceError("Unable to persist FAQ outcome") from exc
        if count is None:
            # An agent took over or the conversation closed during generation.
            updates["suppress_auto_response"] = True
            updates["consecutive_low_confidence"] = 0
            return
        updates["consecutive_low_confidence"] = count

    async def handle(
        self,
        state: ConversationState,
        tenant: TenantContext,
    ) -> ConversationState:
        """Process FAQ query through the full RAG pipeline.

        Args:
            state: Current conversation state with query and language.
            tenant: Tenant context for Qdrant collection and Gemini billing.

        Returns:
            Partial state update with response, chunk_ids, confidence,
            and retrieved_chunks.
        """
        query = state.get("query", "")
        language = state.get("language", "fr")
        updates: dict = {}
        low_confidence = True

        try:
            # Step 1: Retrieve chunks from Qdrant
            safe_query = get_pii_masker().mask(query).masked_text
            retrieval_result = await self._retrieval.retrieve(
                tenant,
                safe_query,
                language=language,
                allow_language_fallback=True,
            )

            # Step 2: No chunks → short-circuit with "no_answer"
            if not retrieval_result.chunks:
                updates["response"] = PromptTemplates.get_message(
                    "no_answer",
                    language,
                )
                updates["confidence"] = 0.0
                updates["chunk_ids"] = []
                updates["retrieved_chunks"] = []
                self._logger.info(
                    "faq_no_chunks",
                    tenant=tenant.slug,
                    query_length=len(query),
                )
                # Record exactly once outside the provider-error handler.
                await self._record_outcome(state, tenant, updates, low=True)
                return updates  # type: ignore[return-value]

            # Step 3: Build conversation history (last 5 messages)
            raw_messages = state.get("messages", [])
            history = [
                {
                    "role": m.get("role", "user") if isinstance(m, dict) else "user",
                    "content": m.get("content", "") if isinstance(m, dict) else str(m),
                }
                for m in raw_messages[-5:]
            ]

            # Step 4: Generate answer (pass chunks to skip double retrieval)
            gen_request = GenerationRequest(
                query=query,
                language=language,
                conversation_history=history,
                chunks=retrieval_result.chunks,
            )
            gen_response = await self._generation.generate(tenant, gen_request)

            # Step 5: Update state with results
            updates["response"] = gen_response.answer
            updates["chunk_ids"] = gen_response.chunk_ids
            updates["sources"] = gen_response.sources
            updates["confidence"] = gen_response.confidence
            low_confidence = gen_response.confidence < _LOW_CONFIDENCE_THRESHOLD
            updates["retrieved_chunks"] = [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content[:200],
                    "score": c.score,
                }
                for c in retrieval_result.chunks
            ]

            self._logger.info(
                "faq_response_generated",
                tenant=tenant.slug,
                confidence=gen_response.confidence,
                chunks_used=len(gen_response.chunk_ids),
                latency_ms=gen_response.latency_ms,
            )

        except FAQOutcomePersistenceError:
            raise
        except Exception as exc:
            self._logger.error(
                "faq_agent_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            updates["error"] = str(exc)
            updates["response"] = PromptTemplates.get_message(
                "error_generic",
                language,
            )
            updates["confidence"] = 0.0
            updates["chunk_ids"] = []
            low_confidence = True

        await self._record_outcome(state, tenant, updates, low=low_confidence)
        return updates  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_faq_agent: FAQAgent | None = None


def get_faq_agent() -> FAQAgent:
    """Get or create the FAQAgent singleton."""
    global _faq_agent  # noqa: PLW0603
    if _faq_agent is None:
        _faq_agent = FAQAgent(
            retrieval=get_retrieval_service(),
            generation=get_generation_service(),
        )
    return _faq_agent
