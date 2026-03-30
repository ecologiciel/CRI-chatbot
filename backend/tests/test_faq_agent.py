"""Tests for FAQAgent — LangGraph FAQ node."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.tenant import TenantContext
from app.schemas.rag import GenerationResponse, RetrievalResult
from app.services.orchestrator.faq_agent import FAQAgent
from app.services.orchestrator.state import ConversationState
from app.services.rag.prompts import PromptTemplates

# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_state(**overrides) -> ConversationState:
    """Create a minimal ConversationState for testing."""
    state: ConversationState = {
        "tenant_slug": "rabat",
        "phone": "+212600000000",
        "language": "fr",
        "intent": "faq",
        "query": "Comment créer une SARL ?",
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
        "consecutive_low_confidence": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _make_chunk(chunk_id="chunk_1", score=0.85, content="Info about SARL"):
    """Create a mock RetrievedChunk (frozen dataclass)."""
    chunk = MagicMock()
    chunk.chunk_id = chunk_id
    chunk.document_id = str(uuid.uuid4())
    chunk.content = content
    chunk.score = score
    chunk.metadata = {"title": "Création SARL"}
    return chunk


def _make_retrieval_result(chunks=None, confidence=0.85):
    """Create a RetrievalResult with the given chunks."""
    if chunks is None:
        chunks = [
            _make_chunk("chunk_1", 0.90),
            _make_chunk("chunk_2", 0.85),
            _make_chunk("chunk_3", 0.80),
        ]
    return MagicMock(
        spec=RetrievalResult,
        chunks=chunks,
        confidence=confidence,
        is_confident=confidence >= 0.7,
    )


def _make_generation_response(
    answer="Pour créer une SARL, vous devez...",
    chunk_ids=None,
    confidence=0.85,
):
    """Create a GenerationResponse."""
    return GenerationResponse(
        answer=answer,
        language="fr",
        chunk_ids=chunk_ids or ["chunk_1", "chunk_2"],
        confidence=confidence,
        is_confident=confidence >= 0.7,
        disclaimer=None,
        model="gemini-2.5-flash",
        input_tokens=200,
        output_tokens=150,
        total_tokens=350,
        latency_ms=850.0,
    )


def _make_faq_agent(mock_retrieval=None, mock_generation=None):
    """Create FAQAgent with mocked dependencies."""
    retrieval = mock_retrieval or AsyncMock()
    generation = mock_generation or AsyncMock()
    return FAQAgent(retrieval=retrieval, generation=generation), retrieval, generation


# --- Tests ---


class TestFAQAgent:
    """FAQAgent test suite."""

    @pytest.mark.asyncio
    async def test_faq_agent_success(self):
        """Full RAG pipeline: retrieval → generation → state updated."""
        retrieval_result = _make_retrieval_result()
        gen_response = _make_generation_response()

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(query="Comment créer une SARL ?")

        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == "Pour créer une SARL, vous devez..."
        assert result["chunk_ids"] == ["chunk_1", "chunk_2"]
        assert result["confidence"] == 0.85
        assert len(result["retrieved_chunks"]) == 3
        assert result["retrieved_chunks"][0]["chunk_id"] == "chunk_1"
        mock_retrieval.retrieve.assert_awaited_once()
        mock_generation.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_faq_agent_no_chunks(self):
        """No chunks retrieved → 'no_answer' message, confidence 0."""
        retrieval_result = _make_retrieval_result(chunks=[], confidence=0.0)

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(query="Quel est le sens de la vie ?")

        result = await agent.handle(state, TEST_TENANT)

        expected_msg = PromptTemplates.get_message("no_answer", "fr")
        assert result["response"] == expected_msg
        assert result["confidence"] == 0.0
        assert result["chunk_ids"] == []
        # Generation should NOT be called when no chunks
        mock_generation.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_faq_agent_error_handling(self):
        """Retrieval raises exception → error set, 'no_answer' response."""
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(
            side_effect=RuntimeError("Qdrant connection failed"),
        )
        mock_generation = AsyncMock()

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(query="Test query")

        result = await agent.handle(state, TEST_TENANT)

        assert result["error"] == "Qdrant connection failed"
        expected_msg = PromptTemplates.get_message("no_answer", "fr")
        assert result["response"] == expected_msg
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_faq_agent_history_truncated(self):
        """10 messages in state → only last 5 passed to GenerationRequest."""
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(10)
        ]
        retrieval_result = _make_retrieval_result()
        gen_response = _make_generation_response()

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(messages=messages)

        await agent.handle(state, TEST_TENANT)

        # Inspect the GenerationRequest passed to generate()
        call_args = mock_generation.generate.call_args
        gen_request = call_args[0][1]  # positional arg: (tenant, request)
        assert len(gen_request.conversation_history) == 5
        assert gen_request.conversation_history[0]["content"] == "msg 5"

    @pytest.mark.asyncio
    async def test_faq_agent_passes_chunks_to_generation(self):
        """Chunks passed to GenerationRequest to avoid double retrieval."""
        chunks = [_make_chunk("c1", 0.9), _make_chunk("c2", 0.8)]
        retrieval_result = _make_retrieval_result(chunks=chunks, confidence=0.85)
        gen_response = _make_generation_response()

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state()

        await agent.handle(state, TEST_TENANT)

        call_args = mock_generation.generate.call_args
        gen_request = call_args[0][1]
        # Chunks must be passed to skip internal retrieval
        assert gen_request.chunks is not None
        assert len(gen_request.chunks) == 2

    @pytest.mark.asyncio
    async def test_faq_agent_arabic_language(self):
        """Arabic language propagated to retrieval and generation."""
        retrieval_result = _make_retrieval_result()
        gen_response = _make_generation_response()

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(language="ar", query="كيف أنشئ شركة؟")

        await agent.handle(state, TEST_TENANT)

        # Check language passed to retrieval
        ret_call = mock_retrieval.retrieve.call_args
        assert ret_call.kwargs["language"] == "ar"

        # Check language passed to generation
        gen_call = mock_generation.generate.call_args
        gen_request = gen_call[0][1]
        assert gen_request.language == "ar"


class TestConsecutiveLowConfidence:
    """Wave 17: FAQAgent consecutive_low_confidence counter tracking."""

    @pytest.mark.asyncio
    async def test_low_confidence_increments_counter(self):
        """Low confidence (< 0.5) → counter incremented."""
        retrieval_result = _make_retrieval_result(confidence=0.3)
        gen_response = _make_generation_response(confidence=0.3)

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(consecutive_low_confidence=1)

        result = await agent.handle(state, TEST_TENANT)

        assert result["consecutive_low_confidence"] == 2

    @pytest.mark.asyncio
    async def test_high_confidence_resets_counter(self):
        """High confidence (>= 0.5) → counter reset to 0."""
        retrieval_result = _make_retrieval_result(confidence=0.85)
        gen_response = _make_generation_response(confidence=0.85)

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(consecutive_low_confidence=2)

        result = await agent.handle(state, TEST_TENANT)

        assert result["consecutive_low_confidence"] == 0

    @pytest.mark.asyncio
    async def test_no_chunks_increments_counter(self):
        """No retrieval chunks → confidence 0.0 → counter incremented."""
        retrieval_result = _make_retrieval_result(chunks=[], confidence=0.0)

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        mock_generation = AsyncMock()

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(consecutive_low_confidence=0)

        result = await agent.handle(state, TEST_TENANT)

        assert result["consecutive_low_confidence"] == 1

    @pytest.mark.asyncio
    async def test_error_increments_counter(self):
        """Retrieval error → counter incremented."""
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(
            side_effect=RuntimeError("Qdrant down"),
        )
        mock_generation = AsyncMock()

        agent, _, _ = _make_faq_agent(mock_retrieval, mock_generation)
        state = _make_state(consecutive_low_confidence=1)

        result = await agent.handle(state, TEST_TENANT)

        assert result["consecutive_low_confidence"] == 2
