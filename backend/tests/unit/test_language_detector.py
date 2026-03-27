"""Unit tests for LanguageDetectionService — heuristic and Gemini fallback."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.enums import Language
from app.services.ai.language import LanguageDetectionService

_GEMINI_PATCH = "app.services.ai.gemini.get_gemini_service"


class TestArabicHeuristic:
    """Arabic Unicode character ratio detection."""

    @pytest.mark.asyncio
    async def test_arabic_above_threshold(self, tenant_context):
        """Text with >= 30% Arabic chars returns Language.ar."""
        service = LanguageDetectionService()
        result = await service.detect("مرحبا كيف يمكنني إنشاء شركة", tenant_context)

        assert result.language == Language.ar
        assert result.method == "heuristic_arabic"
        assert result.confidence > 0.3


class TestFrenchEnglishHeuristic:
    """French vs English indicator word counting."""

    @pytest.mark.asyncio
    async def test_french_dominates(self, tenant_context):
        """French indicators 2x English triggers Language.fr."""
        service = LanguageDetectionService()
        result = await service.detect(
            "Je voudrais créer une entreprise dans le secteur du tourisme",
            tenant_context,
        )

        assert result.language == Language.fr
        assert result.method == "heuristic_french"

    @pytest.mark.asyncio
    async def test_english_dominates(self, tenant_context):
        """English indicators 2x French triggers Language.en."""
        service = LanguageDetectionService()
        result = await service.detect(
            "I would like to create a company with this business plan",
            tenant_context,
        )

        assert result.language == Language.en
        assert result.method == "heuristic_english"


class TestDefaultFallback:
    """Short text and unknown text default to French."""

    @pytest.mark.asyncio
    async def test_short_text_defaults_to_french(self, tenant_context):
        """Text < 3 chars returns Language.fr with method='default'."""
        service = LanguageDetectionService()
        result = await service.detect("ok", tenant_context)

        assert result.language == Language.fr
        assert result.method == "default"
        assert result.confidence == 0.5


class TestGeminiFallback:
    """Gemini fallback for ambiguous text."""

    @pytest.mark.asyncio
    async def test_gemini_fallback_on_ambiguous(self, tenant_context):
        """Text with no clear indicators uses Gemini."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="fr")

        with patch(_GEMINI_PATCH, return_value=mock_gemini):
            service = LanguageDetectionService()
            result = await service.detect("12345 67890", tenant_context)

        assert result.language == Language.fr
        assert result.method == "gemini"
        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_gemini_unexpected_value_defaults(self, tenant_context):
        """Gemini returning 'de' (not fr/ar/en) falls back to default."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="de")

        with patch(_GEMINI_PATCH, return_value=mock_gemini):
            service = LanguageDetectionService()
            result = await service.detect("12345 67890", tenant_context)

        assert result.language == Language.fr
        assert result.method == "default"
