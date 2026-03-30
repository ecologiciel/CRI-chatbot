"""FAQAgent — LangGraph node for FAQ queries via the full RAG pipeline.

Pipeline: retrieve chunks (Qdrant) → generate answer (Gemini) → update state.
Pre-retrieved chunks are passed to GenerationService to avoid double retrieval.
"""

from __future__ import annotations

import structlog

from app.core.tenant import TenantContext
from app.schemas.rag import GenerationRequest
from app.services.orchestrator.state import ConversationState
from app.services.rag.generation import GenerationService, get_generation_service
from app.services.rag.prompts import PromptTemplates
from app.services.rag.retrieval import RetrievalService, get_retrieval_service

logger = structlog.get_logger()

# Matches EscalationService.LOW_CONFIDENCE_THRESHOLD — kept local to avoid
# circular imports (graph → escalation → … → graph).
_LOW_CONFIDENCE_THRESHOLD = 0.5


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

        try:
            # Step 1: Retrieve chunks from Qdrant
            retrieval_result = await self._retrieval.retrieve(
                tenant,
                query,
                language=language,
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
                updates["consecutive_low_confidence"] = (
                    state.get("consecutive_low_confidence", 0) + 1
                )
                self._logger.info(
                    "faq_no_chunks",
                    tenant=tenant.slug,
                    query_length=len(query),
                )
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
            updates["confidence"] = gen_response.confidence
            if gen_response.confidence < _LOW_CONFIDENCE_THRESHOLD:
                updates["consecutive_low_confidence"] = (
                    state.get("consecutive_low_confidence", 0) + 1
                )
            else:
                updates["consecutive_low_confidence"] = 0
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

        except Exception as exc:
            self._logger.error(
                "faq_agent_error",
                error=str(exc),
                tenant=tenant.slug,
            )
            updates["error"] = str(exc)
            updates["response"] = PromptTemplates.get_message(
                "no_answer",
                language,
            )
            updates["confidence"] = 0.0
            updates["chunk_ids"] = []
            updates["consecutive_low_confidence"] = state.get("consecutive_low_confidence", 0) + 1

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
