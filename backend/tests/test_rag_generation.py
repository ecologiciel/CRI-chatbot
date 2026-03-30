"""Tests for GenerationService — retrieval, Gemini, and language detection mocked."""

import os
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before any app imports
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("REDIS_PASSWORD", "test")

from app.core.exceptions import GeminiError, GenerationError
from app.core.tenant import TenantContext
from app.schemas.ai import GeminiResponse
from app.schemas.rag import (
    GenerationRequest,
    RetrievalResult,
    RetrievedChunk,
)
from app.services.rag.prompts import PromptTemplates

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_chunks(n: int = 3, score: float = 0.9) -> list[RetrievedChunk]:
    """Create sample RetrievedChunk instances."""
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{i}",
            document_id=f"doc-{i}",
            content=f"Contenu du chunk numero {i} sur les procedures.",
            score=score - (i * 0.05),
            metadata={"title": f"Document {i}", "language": "fr"},
        )
        for i in range(n)
    ]


def _make_gemini_response(text: str = "Voici la reponse.") -> GeminiResponse:
    """Create a mock GeminiResponse."""
    return GeminiResponse(
        text=text,
        input_tokens=500,
        output_tokens=100,
        total_tokens=600,
        model="gemini-2.5-flash",
        latency_ms=850.0,
        finish_reason="STOP",
    )


@dataclass(frozen=True, slots=True)
class _FakeLanguageResult:
    """Minimal stand-in for LanguageResult."""

    language: MagicMock  # .value -> "fr"
    confidence: float
    method: str


def _make_language_result(lang: str = "fr") -> _FakeLanguageResult:
    """Create a fake LanguageResult."""
    lang_mock = MagicMock()
    lang_mock.value = lang
    return _FakeLanguageResult(language=lang_mock, confidence=0.95, method="heuristic")


def _make_retrieval_result(
    chunks: list[RetrievedChunk] | None = None,
    confidence: float = 0.85,
    is_confident: bool = True,
) -> RetrievalResult:
    """Create a RetrievalResult."""
    if chunks is None:
        chunks = _make_chunks()
    return RetrievalResult(
        chunks=chunks,
        confidence=confidence,
        query_embedding=[0.5] * 768,
        total_results=len(chunks),
        is_confident=is_confident,
    )


def _make_generation_service(
    mock_retrieval=None,
    mock_gemini=None,
    mock_language=None,
):
    """Create GenerationService with mocked dependencies."""
    if mock_retrieval is None:
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=_make_retrieval_result())

    if mock_gemini is None:
        mock_gemini = MagicMock()
        mock_gemini.generate = AsyncMock(return_value=_make_gemini_response())

    if mock_language is None:
        mock_language = MagicMock()
        mock_language.detect = AsyncMock(return_value=_make_language_result())

    with (
        patch("app.services.rag.generation.get_retrieval_service", return_value=mock_retrieval),
        patch("app.services.rag.generation.get_gemini_service", return_value=mock_gemini),
        patch("app.services.rag.generation.get_language_service", return_value=mock_language),
    ):
        from app.services.rag.generation import GenerationService

        service = GenerationService()

    return service, mock_retrieval, mock_gemini, mock_language


# ---------------------------------------------------------------------------
# Tests — Full pipeline
# ---------------------------------------------------------------------------


class TestGenerationSuccess:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_response(self):
        """Happy path: query -> retrieve -> generate -> response with chunk_ids."""
        service, mock_retrieval, mock_gemini, _ = _make_generation_service()

        request = GenerationRequest(query="Quelles sont les incitations fiscales ?")
        response = await service.generate(TEST_TENANT, request)

        assert response.answer == "Voici la reponse."
        assert response.language == "fr"
        assert response.chunk_ids == ["chunk-0", "chunk-1", "chunk-2"]
        assert response.confidence == 0.85
        assert response.is_confident is True
        assert response.disclaimer is None
        assert response.model == "gemini-2.5-flash"
        assert response.input_tokens == 500
        assert response.output_tokens == 100
        assert response.trace_id is not None

        mock_retrieval.retrieve.assert_awaited_once()
        mock_gemini.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_pre_retrieved_chunks_skips_retrieval(self):
        """When chunks are provided, RetrievalService.retrieve is NOT called."""
        chunks = _make_chunks(2, score=0.92)
        service, mock_retrieval, mock_gemini, _ = _make_generation_service()

        request = GenerationRequest(
            query="Comment creer une entreprise ?",
            language="fr",
            chunks=chunks,
        )
        response = await service.generate(TEST_TENANT, request)

        assert response.chunk_ids == ["chunk-0", "chunk-1"]
        mock_retrieval.retrieve.assert_not_awaited()
        mock_gemini.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_language_auto_detection(self):
        """When no language provided, LanguageDetectionService.detect() is called."""
        mock_language = MagicMock()
        mock_language.detect = AsyncMock(return_value=_make_language_result("ar"))
        service, _, mock_gemini, _ = _make_generation_service(mock_language=mock_language)

        request = GenerationRequest(query="What are the investment incentives?")
        response = await service.generate(TEST_TENANT, request)

        assert response.language == "ar"
        mock_language.detect.assert_awaited_once()

        # Verify Arabic system prompt was used
        call_args = mock_gemini.generate.call_args
        gemini_request = call_args[0][0]
        assert gemini_request.system_instruction is not None
        assert "CRI" in gemini_request.system_instruction


# ---------------------------------------------------------------------------
# Tests — Confidence
# ---------------------------------------------------------------------------


class TestGenerationConfidence:
    @pytest.mark.asyncio
    async def test_low_confidence_adds_disclaimer(self):
        """Confidence < 0.7 -> disclaimer set, is_confident=False."""
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(
            return_value=_make_retrieval_result(
                chunks=_make_chunks(2, score=0.5),
                confidence=0.45,
                is_confident=False,
            )
        )
        service, _, _, _ = _make_generation_service(mock_retrieval=mock_retrieval)

        request = GenerationRequest(query="Question ambigue", language="fr")
        response = await service.generate(TEST_TENANT, request)

        assert response.is_confident is False
        assert response.disclaimer is not None
        assert "informations partielles" in response.disclaimer

    @pytest.mark.asyncio
    async def test_no_chunks_returns_no_answer(self):
        """0 chunks -> no_answer message, confidence=0.0."""
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(
            return_value=_make_retrieval_result(
                chunks=[],
                confidence=0.0,
                is_confident=False,
            )
        )
        service, _, mock_gemini, _ = _make_generation_service(mock_retrieval=mock_retrieval)

        request = GenerationRequest(query="Unrelated question", language="fr")
        response = await service.generate(TEST_TENANT, request)

        assert response.confidence == 0.0
        assert response.is_confident is False
        assert "contacter directement le CRI" in response.answer
        assert response.model == "none"
        # Gemini should NOT be called when there are no chunks
        mock_gemini.generate.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests — PII Anonymization
# ---------------------------------------------------------------------------


class TestAnonymization:
    @pytest.mark.asyncio
    async def test_cin_anonymized(self):
        """CIN pattern in chunk content is replaced with [CIN] before Gemini call."""
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="Le dossier de AB123456 a ete valide.",
                score=0.9,
                metadata={"title": "Test"},
            )
        ]
        service, _, mock_gemini, _ = _make_generation_service()

        request = GenerationRequest(query="Mon dossier ?", language="fr", chunks=chunks)
        await service.generate(TEST_TENANT, request)

        # Inspect the contents sent to Gemini
        call_args = mock_gemini.generate.call_args
        gemini_request = call_args[0][0]
        assert "AB123456" not in gemini_request.contents
        assert "[CIN]" in gemini_request.contents

    @pytest.mark.asyncio
    async def test_phone_anonymized(self):
        """+212 phone number is replaced with [TELEPHONE]."""
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="Appelez le +212612345678 pour plus d'infos.",
                score=0.9,
                metadata={"title": "Test"},
            )
        ]
        service, _, mock_gemini, _ = _make_generation_service()

        request = GenerationRequest(query="Contact ?", language="fr", chunks=chunks)
        await service.generate(TEST_TENANT, request)

        call_args = mock_gemini.generate.call_args
        gemini_request = call_args[0][0]
        assert "+212612345678" not in gemini_request.contents
        assert "[TELEPHONE]" in gemini_request.contents

    @pytest.mark.asyncio
    async def test_email_anonymized(self):
        """Email address is replaced with [EMAIL]."""
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="Contactez info@example.com pour assistance.",
                score=0.9,
                metadata={"title": "Test"},
            )
        ]
        service, _, mock_gemini, _ = _make_generation_service()

        request = GenerationRequest(query="Email ?", language="fr", chunks=chunks)
        await service.generate(TEST_TENANT, request)

        call_args = mock_gemini.generate.call_args
        gemini_request = call_args[0][0]
        assert "info@example.com" not in gemini_request.contents
        assert "[EMAIL]" in gemini_request.contents


# ---------------------------------------------------------------------------
# Tests — Prompt Templates
# ---------------------------------------------------------------------------


class TestPromptTemplates:
    def test_system_prompt_french_contains_rules(self):
        """French system prompt contains CRI rules and vouvoiement."""
        prompt = PromptTemplates.get_system_prompt("fr")
        assert "Centre Regional d'Investissement" in prompt or "CRI" in prompt
        assert "Vouvoiement" in prompt
        assert "UNIQUEMENT" in prompt

    def test_system_prompt_arabic_contains_rules(self):
        """Arabic system prompt contains Arabic CRI rules."""
        prompt = PromptTemplates.get_system_prompt("ar")
        assert "CRI" in prompt

    def test_build_context_formats_correctly(self):
        """3 chunks + history -> XML-tagged context string."""
        from app.schemas.rag import ConversationTurn

        chunks = _make_chunks(3)
        history = [
            ConversationTurn(role="user", content="Bonjour"),
            ConversationTurn(role="assistant", content="Comment puis-je vous aider ?"),
        ]
        result = PromptTemplates.build_context(chunks, history, "Ma question ?")

        assert "<context>" in result
        assert "</context>" in result
        assert "<history>" in result
        assert "<question>" in result
        assert "Ma question ?" in result
        assert "Document 0" in result  # chunk title
        assert "Utilisateur: Bonjour" in result

    def test_get_message_multilingual(self):
        """get_message returns the correct language variant."""
        greeting_ar = PromptTemplates.get_message("greeting", "ar")
        assert len(greeting_ar) > 0

        greeting_en = PromptTemplates.get_message("greeting", "en")
        assert "CRI virtual assistant" in greeting_en

        # Unknown language falls back to French
        greeting_unknown = PromptTemplates.get_message("greeting", "zh")
        assert "assistant virtuel du CRI" in greeting_unknown


# ---------------------------------------------------------------------------
# Tests — Error handling
# ---------------------------------------------------------------------------


class TestGenerationError:
    @pytest.mark.asyncio
    async def test_gemini_failure_raises_generation_error(self):
        """GeminiError during generation is wrapped in GenerationError."""
        mock_gemini = MagicMock()
        mock_gemini.generate = AsyncMock(side_effect=GeminiError("API quota exceeded"))
        service, _, _, _ = _make_generation_service(mock_gemini=mock_gemini)

        request = GenerationRequest(query="Test question", language="fr")
        with pytest.raises(GenerationError, match="RAG generation failed"):
            await service.generate(TEST_TENANT, request)
