"""Unit tests for FAQAgent — RAG pipeline orchestration in LangGraph."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.rag import GenerationResponse, RetrievedChunk, RetrievalResult
from app.services.orchestrator.faq_agent import FAQAgent
from tests.unit.conftest import make_conversation_state


def _make_chunks(count=3, score=0.85):
    """Create RetrievedChunk instances."""
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{i}", document_id=f"doc-{i}",
            content=f"Chunk {i} text about entreprise.", score=score,
            metadata={"title": "Test"},
        )
        for i in range(count)
    ]


def _make_agent(
    retrieval_chunks=None,
    retrieval_confidence=0.85,
    retrieval_error=False,
    generation_response=None,
):
    """Create FAQAgent with mocked retrieval and generation."""
    mock_retrieval = AsyncMock()
    if retrieval_error:
        mock_retrieval.retrieve = AsyncMock(
            side_effect=RuntimeError("Qdrant timeout"),
        )
    else:
        chunks = retrieval_chunks if retrieval_chunks is not None else _make_chunks()
        mock_retrieval.retrieve = AsyncMock(
            return_value=RetrievalResult(
                chunks=chunks,
                confidence=retrieval_confidence,
                query_embedding=[0.1] * 768,
                total_results=len(chunks),
                is_confident=retrieval_confidence >= 0.7,
            ),
        )

    mock_generation = AsyncMock()
    mock_generation.generate = AsyncMock(
        return_value=generation_response or GenerationResponse(
            answer="Voici la procédure pour créer une SARL.",
            language="fr", chunk_ids=["chunk-0", "chunk-1", "chunk-2"],
            confidence=0.85, is_confident=True, disclaimer=None,
            model="gemini-2.5-flash", input_tokens=50, output_tokens=30,
            total_tokens=80, latency_ms=200.0,
        ),
    )

    return FAQAgent(retrieval=mock_retrieval, generation=mock_generation), mock_retrieval, mock_generation


class TestFAQSuccess:
    """Successful FAQ handling."""

    @pytest.mark.asyncio
    async def test_success_updates_state(self, tenant_context):
        """FAQ response sets response, chunk_ids, confidence in state."""
        agent, _, _ = _make_agent()
        state = make_conversation_state(
            query="Comment créer une SARL?", language="fr",
        )

        result = await agent.handle(state, tenant_context)

        assert "Voici la procédure" in result["response"]
        assert len(result["chunk_ids"]) == 3
        assert result["confidence"] == 0.85


class TestNoChunks:
    """No chunks found returns fallback message."""

    @pytest.mark.asyncio
    async def test_no_chunks_returns_no_answer(self, tenant_context):
        """Empty retrieval: no_answer message, generation NOT called."""
        agent, _, generation = _make_agent(
            retrieval_chunks=[], retrieval_confidence=0.0,
        )
        state = make_conversation_state(query="Topic inconnu")

        result = await agent.handle(state, tenant_context)

        assert result["confidence"] == 0.0
        assert result["chunk_ids"] == []
        assert result["response"] != ""  # Should have a fallback message
        generation.generate.assert_not_called()


class TestRetrievalError:
    """Retrieval error sets error field."""

    @pytest.mark.asyncio
    async def test_retrieval_error_sets_error(self, tenant_context):
        """RuntimeError: error field set, fallback response."""
        agent, _, _ = _make_agent(retrieval_error=True)
        state = make_conversation_state(query="Test")

        result = await agent.handle(state, tenant_context)

        assert result["error"] is not None
        assert "Qdrant timeout" in result["error"]
        assert result["confidence"] == 0.0


class TestHistoryTruncation:
    """Conversation history is truncated to last 5 messages."""

    @pytest.mark.asyncio
    async def test_history_truncated_to_5(self, tenant_context):
        """10 messages in state → only last 5 sent to generation."""
        agent, _, generation = _make_agent()
        messages = [
            {"role": "user", "content": f"msg-{i}"} for i in range(10)
        ]
        state = make_conversation_state(
            query="Latest question", messages=messages,
        )

        await agent.handle(state, tenant_context)

        call_args = generation.generate.call_args
        gen_request = call_args[0][1]  # Second positional arg is the request
        assert len(gen_request.conversation_history) == 5


class TestChunksPassedToGeneration:
    """Chunks from retrieval are passed to generation to avoid double retrieval."""

    @pytest.mark.asyncio
    async def test_chunks_forwarded(self, tenant_context):
        """Retrieved chunks are included in GenerationRequest."""
        agent, _, generation = _make_agent()
        state = make_conversation_state(query="Test")

        await agent.handle(state, tenant_context)

        call_args = generation.generate.call_args
        gen_request = call_args[0][1]
        assert gen_request.chunks is not None
        assert len(gen_request.chunks) == 3
