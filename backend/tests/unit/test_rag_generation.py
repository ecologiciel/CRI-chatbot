"""Unit tests for GenerationService — full RAG generation pipeline."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import GeminiError, GenerationError
from app.models.enums import Language
from app.schemas.ai import GeminiResponse
from app.schemas.rag import GenerationRequest, RetrievalResult, RetrievedChunk
from app.services.ai.language import LanguageResult
from app.services.rag.generation import GenerationService

_RETRIEVAL_PATCH = "app.services.rag.generation.get_retrieval_service"
_GEMINI_PATCH = "app.services.rag.generation.get_gemini_service"
_LANGUAGE_PATCH = "app.services.rag.generation.get_language_service"


def _make_chunks(count=3, score=0.85):
    """Create RetrievedChunk instances."""
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{i}",
            document_id=f"doc-{i}",
            content=f"Chunk content {i}. Pour créer une entreprise SARL.",
            score=score,
            metadata={"title": "Test", "language": "fr"},
        )
        for i in range(count)
    ]


def _make_retrieval_result(chunks=None, confidence=0.85):
    """Create a RetrievalResult."""
    chunks = chunks if chunks is not None else _make_chunks()
    return RetrievalResult(
        chunks=chunks,
        confidence=confidence,
        query_embedding=[0.1] * 768,
        total_results=len(chunks),
        is_confident=confidence >= 0.7,
    )


def _make_gemini_response(text="Réponse générée."):
    """Create a GeminiResponse."""
    return GeminiResponse(
        text=text,
        input_tokens=50,
        output_tokens=30,
        total_tokens=80,
        model="gemini-2.5-flash",
        latency_ms=200.0,
    )


def _make_service(
    retrieval_result=None,
    gemini_response=None,
    gemini_error=False,
):
    """Create GenerationService with mocked dependencies."""
    mock_retrieval = AsyncMock()
    mock_retrieval.retrieve = AsyncMock(
        return_value=retrieval_result or _make_retrieval_result(),
    )

    mock_gemini = AsyncMock()
    if gemini_error:
        mock_gemini.generate = AsyncMock(side_effect=GeminiError("API down"))
    else:
        mock_gemini.generate = AsyncMock(
            return_value=gemini_response or _make_gemini_response(),
        )

    mock_language = AsyncMock()
    mock_language.detect = AsyncMock(
        return_value=LanguageResult(
            language=Language.fr, confidence=0.9, method="heuristic_french"
        ),
    )

    with (
        patch(_RETRIEVAL_PATCH, return_value=mock_retrieval),
        patch(_GEMINI_PATCH, return_value=mock_gemini),
        patch(_LANGUAGE_PATCH, return_value=mock_language),
    ):
        service = GenerationService()
        return service, mock_retrieval, mock_gemini


class TestFullPipeline:
    """Full RAG generation pipeline success."""

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, tenant_context):
        """query → retrieve → generate → response with chunk_ids."""
        service, retrieval, gemini = _make_service()
        request = GenerationRequest(query="Comment créer une SARL?", language="fr")

        result = await service.generate(tenant_context, request)

        assert "Réponse générée" in result.answer
        assert len(result.chunk_ids) == 3
        assert result.confidence == 0.85
        assert result.is_confident is True
        assert result.model == "gemini-2.5-flash"


class TestNoChunksFallback:
    """No chunks → fallback message, Gemini NOT called."""

    @pytest.mark.asyncio
    async def test_no_chunks_returns_fallback(self, tenant_context):
        """Empty retrieval returns no_answer message; Gemini not called."""
        service, _, gemini = _make_service(
            retrieval_result=_make_retrieval_result(chunks=[], confidence=0.0),
        )
        request = GenerationRequest(query="Topic inconnu", language="fr")

        result = await service.generate(tenant_context, request)

        assert result.confidence == 0.0
        assert result.is_confident is False
        assert result.chunk_ids == []
        gemini.generate.assert_not_called()


class TestLowConfidenceDisclaimer:
    """Low confidence adds disclaimer to answer."""

    @pytest.mark.asyncio
    async def test_low_confidence_disclaimer(self, tenant_context):
        """confidence=0.45 prepends a disclaimer."""
        service, _, _ = _make_service(
            retrieval_result=_make_retrieval_result(confidence=0.45),
        )
        request = GenerationRequest(query="Question vague", language="fr")

        result = await service.generate(tenant_context, request)

        assert result.disclaimer is not None
        assert result.is_confident is False


class TestPIIAnonymization:
    """PII is anonymized before sending to Gemini."""

    @pytest.mark.asyncio
    async def test_cin_anonymized_before_gemini(self, tenant_context):
        """CIN in chunk content is replaced with [CIN] in Gemini prompt."""
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="Le client AB123456 doit déposer son dossier.",
                score=0.9,
                metadata={},
            ),
        ]
        service, _, gemini = _make_service(
            retrieval_result=_make_retrieval_result(chunks=chunks, confidence=0.9),
        )
        request = GenerationRequest(
            query="Procédure dépôt",
            language="fr",
            chunks=chunks,
        )

        await service.generate(tenant_context, request)

        # Verify Gemini was called with anonymized content
        call_args = gemini.generate.call_args
        gemini_request = call_args[0][0]
        assert "AB123456" not in gemini_request.contents
        assert "[CIN]" in gemini_request.contents


class TestPreRetrievedChunks:
    """Pre-retrieved chunks skip retrieval call."""

    @pytest.mark.asyncio
    async def test_chunks_in_request_skip_retrieval(self, tenant_context):
        """When chunks are provided in request, retrieval.retrieve is NOT called."""
        chunks = _make_chunks(2, score=0.9)
        service, retrieval, _ = _make_service()
        request = GenerationRequest(
            query="Test",
            language="fr",
            chunks=chunks,
        )

        await service.generate(tenant_context, request)

        retrieval.retrieve.assert_not_called()


class TestGeminiFailure:
    """Gemini errors wrapped in GenerationError."""

    @pytest.mark.asyncio
    async def test_gemini_failure_raises_generation_error(self, tenant_context):
        """GeminiError is wrapped in GenerationError."""
        service, _, _ = _make_service(gemini_error=True)
        request = GenerationRequest(query="Test", language="fr")

        with pytest.raises(GenerationError, match="RAG generation failed"):
            await service.generate(tenant_context, request)
