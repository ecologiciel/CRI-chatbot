"""Tests for LanguageDetectionService.

Covers Arabic/French/English heuristic detection,
Gemini fallback, and default French behavior.
"""

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

# Ensure env vars are set before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-jwt-testing-only")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test_app_secret")

from app.core.tenant import TenantContext
from app.models.enums import Language
from app.services.ai.language import LanguageDetectionService

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat-Salé-Kénitra",
    status="active",
    whatsapp_config=None,
)


class TestArabicDetection:
    """Tests for Arabic Unicode heuristic detection."""

    @pytest.mark.asyncio
    async def test_detect_arabic(self):
        """Pure Arabic text is detected via heuristic."""
        service = LanguageDetectionService()
        text = "مرحبا، أريد معرفة الإجراءات اللازمة لإنشاء شركة"

        result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.ar
        assert result.method == "heuristic_arabic"
        assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_detect_arabic_mixed_with_numbers(self):
        """Arabic text with numbers and punctuation still detected."""
        service = LanguageDetectionService()
        text = "كيف يمكنني تتبع الملف رقم 12345؟"

        result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.ar
        assert result.method == "heuristic_arabic"


class TestFrenchDetection:
    """Tests for French indicator word heuristic."""

    @pytest.mark.asyncio
    async def test_detect_french(self):
        """French text with indicator words is detected via heuristic."""
        service = LanguageDetectionService()
        text = "Bonjour, je voudrais créer une entreprise au Maroc. Quelles sont les démarches?"

        result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "heuristic_french"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_detect_french_short(self):
        """Short French phrase with enough indicators."""
        service = LanguageDetectionService()
        text = "Quelles sont les conditions pour un projet dans la région?"

        result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "heuristic_french"


class TestEnglishDetection:
    """Tests for English indicator word heuristic."""

    @pytest.mark.asyncio
    async def test_detect_english(self):
        """English text with indicator words is detected via heuristic."""
        service = LanguageDetectionService()
        text = "Hello, I would like to know the procedures for creating a company in Morocco"

        result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.en
        assert result.method == "heuristic_english"
        assert result.confidence >= 0.8


class TestGeminiFallback:
    """Tests for Gemini fallback on ambiguous text."""

    @pytest.mark.asyncio
    async def test_detect_ambiguous_uses_gemini(self):
        """Text with no indicators falls back to Gemini."""
        service = LanguageDetectionService()
        # No French/English indicators, no Arabic chars
        text = "SARL 2024 capital 100000 MAD Casablanca"

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="fr")

        with patch(
            "app.services.ai.gemini.get_gemini_service",
            return_value=mock_gemini,
        ):
            result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "gemini"
        assert result.confidence == 0.7
        mock_gemini.generate_simple.assert_called_once()

    @pytest.mark.asyncio
    async def test_gemini_returns_arabic(self):
        """Gemini can return Arabic detection."""
        service = LanguageDetectionService()
        text = "SARL 2024 Rabat 50000"

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="ar")

        with patch(
            "app.services.ai.gemini.get_gemini_service",
            return_value=mock_gemini,
        ):
            result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.ar
        assert result.method == "gemini"

    @pytest.mark.asyncio
    async def test_gemini_error_falls_back_to_default(self):
        """Gemini failure gracefully falls back to French default."""
        service = LanguageDetectionService()
        text = "SARL 2024 capital 100000 MAD"

        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(side_effect=RuntimeError("API Error"))

        with patch(
            "app.services.ai.gemini.get_gemini_service",
            return_value=mock_gemini,
        ):
            result = await service.detect(text, TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "default"


class TestDefaultBehavior:
    """Tests for edge cases and default behavior."""

    @pytest.mark.asyncio
    async def test_default_french_very_short(self):
        """Text shorter than MIN_TEXT_LENGTH defaults to French."""
        service = LanguageDetectionService()

        result = await service.detect("Hi", TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "default"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_default_french_empty(self):
        """Empty/whitespace text defaults to French."""
        service = LanguageDetectionService()

        result = await service.detect("  ", TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "default"

    @pytest.mark.asyncio
    async def test_default_french_single_char(self):
        """Single character defaults to French."""
        service = LanguageDetectionService()

        result = await service.detect("?", TEST_TENANT)

        assert result.language == Language.fr
        assert result.method == "default"


class TestHeuristicEdgeCases:
    """Tests for edge cases in heuristic detection."""

    @pytest.mark.asyncio
    async def test_arabic_below_threshold(self):
        """Mixed text with Arabic below 30% threshold doesn't match Arabic."""
        service = LanguageDetectionService()
        # Mostly Latin with a few Arabic chars
        text = "Hello World Test مرحبا something more latin text here"

        result = await service.detect(text, TEST_TENANT)

        # Should not be Arabic (below threshold)
        assert result.language != Language.ar or result.confidence < 0.3

    @pytest.mark.asyncio
    async def test_numbers_only_no_crash(self):
        """Text with only numbers/punctuation doesn't crash."""
        service = LanguageDetectionService()
        text = "12345 67890 +212"

        # Should not crash, may use gemini or default
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="fr")

        with patch(
            "app.services.ai.gemini.get_gemini_service",
            return_value=mock_gemini,
        ):
            result = await service.detect(text, TEST_TENANT)

        assert result.language in {Language.fr, Language.ar, Language.en}
