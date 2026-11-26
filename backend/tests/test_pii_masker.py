"""Tests for PIIMasker — Moroccan PII detection and masking."""

import pytest

from app.services.guardrails.pii_masker import PIIMasker, PIIMaskResult


class TestCINMasking:
    """Tests for Carte d'Identité Nationale masking."""

    def test_masks_cin_standard(self):
        """Standard CIN (2 letters + 6 digits) is masked."""
        masker = PIIMasker()
        result = masker.mask("Mon CIN AB123456 est valide")

        assert "[CIN_1]" in result.masked_text
        assert "AB123456" not in result.masked_text
        assert result.pii_count == 1
        assert result.pii_found[0].pii_type == "cin"
        assert result.pii_found[0].original == "AB123456"

    def test_masks_cin_single_letter(self):
        """CIN with single letter prefix (1 letter + 5 digits) is masked."""
        masker = PIIMasker()
        result = masker.mask("CIN: Z12345")

        assert "[CIN_1]" in result.masked_text
        assert "Z12345" not in result.masked_text
        assert result.pii_count == 1


class TestPhoneMasking:
    """Tests for Moroccan phone number masking."""

    def test_masks_phone_intl(self):
        """International format (+212) phone number is masked."""
        masker = PIIMasker()
        result = masker.mask("Appelez-moi au +212612345678")

        assert "[PHONE_1]" in result.masked_text
        assert "+212612345678" not in result.masked_text
        assert result.pii_count == 1
        assert result.pii_found[0].pii_type == "phone"

    def test_masks_phone_local(self):
        """Local format (06/07) phone number with spaces is masked."""
        masker = PIIMasker()
        result = masker.mask("Mon numéro: 06 12 34 56 78")

        assert "[PHONE_1]" in result.masked_text
        assert "06 12 34 56 78" not in result.masked_text
        assert result.pii_count == 1

    @pytest.mark.parametrize(
        "number",
        [
            "0522123456",
            "05 22 12 34 56",
            "+212522123456",
            "00212 5 22 12 34 56",
            "+212 (0)5 22 12 34 56",
            "0412345678",
        ],
    )
    def test_masks_fixed_and_additional_mobile_formats(self, number):
        result = PIIMasker().mask(f"Contact : {number}")
        assert result.masked_text == "Contact : [PHONE_1]"
        assert result.pii_found[0].original == number

    def test_special_service_number_is_not_treated_as_personal(self):
        assert PIIMasker().mask("Centre : 080 100 36 37").masked_text == "Centre : 080 100 36 37"

    def test_does_not_match_partial_number_in_a_longer_identifier(self):
        assert PIIMasker().mask("123052212345699").pii_count == 0


class TestEmailMasking:
    """Tests for email address masking."""

    def test_masks_email(self):
        """Standard email address is masked."""
        masker = PIIMasker()
        result = masker.mask("Contactez-nous à contact@cri.ma pour plus d'infos")

        assert "[EMAIL_1]" in result.masked_text
        assert "contact@cri.ma" not in result.masked_text
        assert result.pii_count == 1
        assert result.pii_found[0].pii_type == "email"


class TestAmountMasking:
    """Tests for monetary amount masking."""

    def test_masks_amount_mad(self):
        """Amount with MAD currency is masked."""
        masker = PIIMasker()
        result = masker.mask("Le montant est de 500 000 MAD")

        assert "[AMOUNT_1]" in result.masked_text
        assert "MAD" not in result.masked_text
        assert result.pii_count == 1
        assert result.pii_found[0].pii_type == "amount"


class TestMultiplePII:
    """Tests for texts containing multiple PII types."""

    def test_masks_multiple_types(self):
        """Text with CIN + phone + email → all masked with correct types."""
        masker = PIIMasker()
        text = "Client AB123456, tél: 0612345678, email: user@test.com"
        result = masker.mask(text)

        assert result.pii_count == 3
        assert "AB123456" not in result.masked_text
        assert "0612345678" not in result.masked_text
        assert "user@test.com" not in result.masked_text
        assert "[CIN_1]" in result.masked_text
        assert "[PHONE_1]" in result.masked_text
        assert "[EMAIL_1]" in result.masked_text

        types_found = {m.pii_type for m in result.pii_found}
        assert types_found == {"cin", "phone", "email"}

    def test_unmask_restores_original(self):
        """unmask() reconstructs the original text from masked result."""
        masker = PIIMasker()
        original = "Client AB123456, tél: 0612345678, email: user@test.com"
        result = masker.mask(original)
        restored = masker.unmask(result.masked_text, result.pii_found)

        assert restored == original


class TestNoPII:
    """Tests for clean text without PII."""

    def test_clean_text_unchanged(self):
        """Text without PII is returned unchanged with pii_count=0."""
        masker = PIIMasker()
        text = "Bonjour, comment créer une entreprise au Maroc?"
        result = masker.mask(text)

        assert result.masked_text == text
        assert result.pii_count == 0
        assert result.pii_found == []
        assert isinstance(result, PIIMaskResult)

    def test_empty_text(self):
        """Empty string returns empty result."""
        masker = PIIMasker()
        result = masker.mask("")

        assert result.masked_text == ""
        assert result.pii_count == 0
