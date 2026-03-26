"""Tests for OutputGuardService — PII masking, confidence check, tone validation."""

import os

import pytest

# Ensure env vars are set before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-jwt-testing-only")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test_app_secret")

from app.services.guardrails.output_guard import OutputGuardService


class TestOutputGuardClean:
    """Tests for clean output that passes all checks."""

    @pytest.mark.asyncio
    async def test_clean_output_passes(self):
        """Clean text with high confidence passes with no issues."""
        service = OutputGuardService()
        result = await service.check(
            text="Pour créer une SARL au Maroc, vous devez suivre ces étapes...",
            confidence=0.9,
            language="fr",
        )

        assert result.is_valid is True
        assert result.pii_masked_count == 0
        assert result.confidence_ok is True
        assert result.issues == []
        assert "SARL" in result.cleaned_text


class TestOutputGuardPII:
    """Tests for PII detection in LLM output."""

    @pytest.mark.asyncio
    async def test_pii_masked_in_output(self):
        """CIN leaked in LLM output is masked."""
        service = OutputGuardService()
        result = await service.check(
            text="Le dossier de M. Alami (CIN: AB123456) a été approuvé.",
            confidence=0.9,
            language="fr",
        )

        assert result.is_valid is True
        assert result.pii_masked_count >= 1
        assert "AB123456" not in result.cleaned_text
        assert "[CIN_1]" in result.cleaned_text
        assert any("pii_found" in issue for issue in result.issues)


class TestOutputGuardConfidence:
    """Tests for confidence threshold checking."""

    @pytest.mark.asyncio
    async def test_low_confidence_adds_disclaimer(self):
        """Confidence below threshold appends a disclaimer."""
        service = OutputGuardService()
        result = await service.check(
            text="Je pense que les délais sont de 3 mois.",
            confidence=0.5,
            language="fr",
        )

        assert result.is_valid is True
        assert result.confidence_ok is False
        assert any("low_confidence" in issue for issue in result.issues)
        assert "titre indicatif" in result.cleaned_text

    @pytest.mark.asyncio
    async def test_threshold_boundary_exact(self):
        """Confidence exactly at threshold (0.7) passes."""
        service = OutputGuardService()
        result = await service.check(
            text="Les procédures de création sont disponibles en ligne.",
            confidence=0.7,
            language="fr",
        )

        assert result.confidence_ok is True
        assert not any("low_confidence" in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_low_confidence_arabic_disclaimer(self):
        """Low confidence in Arabic adds Arabic disclaimer."""
        service = OutputGuardService()
        result = await service.check(
            text="أعتقد أن المهلة ثلاثة أشهر.",
            confidence=0.5,
            language="ar",
        )

        assert result.confidence_ok is False
        assert "إرشادية" in result.cleaned_text


class TestOutputGuardTone:
    """Tests for informal tone detection."""

    @pytest.mark.asyncio
    async def test_informal_tone_flagged(self):
        """Internet slang and tutoiement are flagged."""
        service = OutputGuardService()
        result = await service.check(
            text="lol mdr tu es vraiment drôle",
            confidence=0.9,
            language="fr",
        )

        assert result.is_valid is True
        assert any("informal_tone" in issue for issue in result.issues)
        # Should detect both internet_slang and tutoiement
        tone_issues = [i for i in result.issues if "informal_tone" in i]
        assert len(tone_issues) >= 2
