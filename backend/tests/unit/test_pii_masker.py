"""Unit tests for PIIMasker — Moroccan PII detection, masking, and unmask round-trip."""

from app.services.guardrails.pii_masker import PIIMasker


class TestCINMasking:
    """CIN (Carte d'Identité Nationale) pattern detection."""

    def test_masks_cin_standard_two_letters(self):
        """Standard 2-letter CIN (e.g. AB123456) is masked."""
        masker = PIIMasker()
        result = masker.mask("Client CIN AB123456 enregistré")

        assert "[CIN_1]" in result.masked_text
        assert "AB123456" not in result.masked_text
        assert result.pii_count == 1
        assert result.pii_found[0].pii_type == "cin"

    def test_masks_cin_single_letter(self):
        """Single-letter CIN (e.g. Z12345) is masked."""
        masker = PIIMasker()
        result = masker.mask("CIN: Z12345 valide")

        assert "[CIN_1]" in result.masked_text
        assert "Z12345" not in result.masked_text


class TestPhoneMasking:
    """Moroccan phone number pattern detection."""

    def test_masks_phone_international(self):
        """+212 format phone is masked."""
        masker = PIIMasker()
        result = masker.mask("Appelez +212612345678")

        assert "[PHONE_1]" in result.masked_text
        assert "+212612345678" not in result.masked_text
        assert result.pii_found[0].pii_type == "phone"


class TestIBANMasking:
    """Moroccan IBAN pattern detection."""

    def test_masks_iban_moroccan(self):
        """Moroccan IBAN (MA + 26 digits) is masked."""
        masker = PIIMasker()
        iban = "MA12 3456 7890 1234 5678 9012 3456"
        result = masker.mask(f"Virement sur {iban}")

        assert "[IBAN_1]" in result.masked_text
        assert "MA12" not in result.masked_text
        assert result.pii_found[0].pii_type == "iban"


class TestDossierMasking:
    """CRI dossier number pattern detection."""

    def test_masks_dossier_rc(self):
        """Dossier number RC-12345 is masked."""
        masker = PIIMasker()
        result = masker.mask("Dossier RC-12345 en cours")

        assert "[DOSSIER_1]" in result.masked_text
        assert "RC-12345" not in result.masked_text
        assert result.pii_found[0].pii_type == "dossier"


class TestMultiplePII:
    """Texts containing multiple PII types."""

    def test_masks_multiple_types(self):
        """CIN + phone + email all masked with correct token types."""
        masker = PIIMasker()
        text = "Client AB123456, tél: 0612345678, email: user@test.com"
        result = masker.mask(text)

        assert result.pii_count == 3
        types_found = {m.pii_type for m in result.pii_found}
        assert types_found == {"cin", "phone", "email"}
        assert "AB123456" not in result.masked_text


class TestUnmaskRoundTrip:
    """Unmask restores original text."""

    def test_unmask_round_trip(self):
        """mask then unmask restores the original text."""
        masker = PIIMasker()
        original = "Contact AB123456 au 0612345678 ou user@cri.ma"
        result = masker.mask(original)
        restored = masker.unmask(result.masked_text, result.pii_found)

        assert restored == original
