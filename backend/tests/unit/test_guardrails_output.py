"""Unit tests for OutputGuardService — PII masking, confidence disclaimer, tone check."""

from unittest.mock import patch

import pytest

from app.services.guardrails.output_guard import OutputGuardService

# Patch the singleton so OutputGuardService.__init__ gets a real PIIMasker
_PII_PATCH = "app.services.guardrails.output_guard.get_pii_masker"


def _make_guard():
    """Create OutputGuardService with the real PIIMasker (pure regex, no I/O)."""
    from app.services.guardrails.pii_masker import PIIMasker

    with patch(_PII_PATCH, return_value=PIIMasker()):
        return OutputGuardService()


class TestCleanOutput:
    """Clean, high-confidence output passes without issues."""

    @pytest.mark.asyncio
    async def test_clean_high_confidence_passes(self):
        """No PII, high confidence, formal tone → no issues."""
        guard = _make_guard()
        result = await guard.check(
            "Pour créer une SARL, vous devez déposer un dossier au CRI.",
            confidence=0.85,
            language="fr",
        )

        assert result.is_valid is True
        assert result.pii_masked_count == 0
        assert result.confidence_ok is True
        assert result.issues == []


class TestPIIMaskedInOutput:
    """PII in LLM output is masked and flagged."""

    @pytest.mark.asyncio
    async def test_cin_in_response_masked(self):
        """CIN in LLM output is replaced with [CIN_1]."""
        guard = _make_guard()
        result = await guard.check(
            "Le client AB123456 a un dossier en cours.",
            confidence=0.9,
        )

        assert "[CIN_1]" in result.cleaned_text
        assert "AB123456" not in result.cleaned_text
        assert result.pii_masked_count >= 1
        assert any("pii_found" in issue for issue in result.issues)


class TestLowConfidenceDisclaimer:
    """Low confidence appends a trilingual disclaimer."""

    @pytest.mark.asyncio
    async def test_low_confidence_fr_disclaimer(self):
        """confidence=0.5 appends French disclaimer with 'titre indicatif'."""
        guard = _make_guard()
        result = await guard.check(
            "Voici la procédure.", confidence=0.5, language="fr",
        )

        assert result.confidence_ok is False
        assert "titre indicatif" in result.cleaned_text

    @pytest.mark.asyncio
    async def test_low_confidence_ar_disclaimer(self):
        """confidence=0.5 appends Arabic disclaimer."""
        guard = _make_guard()
        result = await guard.check(
            "إليك الإجراء.", confidence=0.5, language="ar",
        )

        assert result.confidence_ok is False
        assert "إرشادية" in result.cleaned_text


class TestInformalTone:
    """Informal language patterns are flagged."""

    @pytest.mark.asyncio
    async def test_tutoiement_and_slang_flagged(self):
        """Tutoiement + internet slang produce issues."""
        guard = _make_guard()
        result = await guard.check(
            "lol tu es au bon endroit mdr",
            confidence=0.9,
        )

        issue_text = " ".join(result.issues)
        assert "tutoiement" in issue_text
        assert "internet_slang" in issue_text
