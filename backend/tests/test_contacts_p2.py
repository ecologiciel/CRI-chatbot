"""Tests unitaires du module Contacts enrichi (CRM Phase 2).

Couvre :
- Validation telephone : pattern E.164, formats marocains
- Validation CIN : pattern marocain
- Constantes d'import : MAX_IMPORT_ROWS, PHONE_ALIASES
- Segmentation : commande STOP, opt-out
"""

from __future__ import annotations

import os
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")


# =====================================================================
# Phone Validation
# =====================================================================


class TestPhoneValidation:
    """Tests de la validation des numeros de telephone E.164."""

    def test_phone_pattern_valid_e164(self):
        """Numero E.164 valide -> match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert PHONE_PATTERN.match("+212612345678")

    def test_phone_pattern_valid_e164_long(self):
        """Numero E.164 long (15 chiffres) -> match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert PHONE_PATTERN.match("+123456789012345")

    def test_phone_pattern_rejects_no_plus(self):
        """Numero sans + -> pas de match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert not PHONE_PATTERN.match("212612345678")

    def test_phone_pattern_rejects_too_short(self):
        """Numero trop court -> pas de match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert not PHONE_PATTERN.match("+1234")

    def test_phone_pattern_rejects_leading_zero(self):
        """Numero commencant par +0 -> pas de match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert not PHONE_PATTERN.match("+0612345678")

    def test_phone_pattern_rejects_letters(self):
        """Numero avec des lettres -> pas de match."""
        from app.services.contact.import_export import PHONE_PATTERN

        assert not PHONE_PATTERN.match("+212abc45678")


# =====================================================================
# CIN Validation
# =====================================================================


class TestCINValidation:
    """Tests de la validation du CIN marocain."""

    def test_cin_pattern_valid_two_letters(self):
        """CIN valide (2 lettres + 6 chiffres) -> match."""
        from app.services.contact.import_export import CIN_PATTERN

        assert CIN_PATTERN.match("AB123456")

    def test_cin_pattern_valid_one_letter(self):
        """CIN valide (1 lettre + 5 chiffres) -> match."""
        from app.services.contact.import_export import CIN_PATTERN

        assert CIN_PATTERN.match("A12345")

    def test_cin_pattern_rejects_lowercase(self):
        """CIN en minuscules -> pas de match."""
        from app.services.contact.import_export import CIN_PATTERN

        assert not CIN_PATTERN.match("ab123456")

    def test_cin_pattern_rejects_too_many_letters(self):
        """CIN avec 3 lettres -> pas de match."""
        from app.services.contact.import_export import CIN_PATTERN

        assert not CIN_PATTERN.match("ABC12345")


# =====================================================================
# Import Constants
# =====================================================================


class TestImportConstants:
    """Tests des constantes d'import."""

    def test_max_import_rows(self):
        """MAX_IMPORT_ROWS est defini a 50 000."""
        from app.services.contact.import_export import MAX_IMPORT_ROWS

        assert MAX_IMPORT_ROWS == 50_000

    def test_batch_size_positive(self):
        """BATCH_SIZE est positif."""
        from app.services.contact.import_export import BATCH_SIZE

        assert BATCH_SIZE > 0

    def test_phone_aliases_include_common_names(self):
        """PHONE_ALIASES contient les noms courants."""
        from app.services.contact.import_export import PHONE_ALIASES

        assert "phone" in PHONE_ALIASES
        assert "telephone" in PHONE_ALIASES
        assert "mobile" in PHONE_ALIASES

    def test_name_aliases_include_common_names(self):
        """NAME_ALIASES contient les noms courants."""
        from app.services.contact.import_export import NAME_ALIASES

        assert "name" in NAME_ALIASES
        assert "nom" in NAME_ALIASES

    def test_language_aliases_include_common_names(self):
        """LANGUAGE_ALIASES contient les noms courants."""
        from app.services.contact.import_export import LANGUAGE_ALIASES

        assert "language" in LANGUAGE_ALIASES
        assert "langue" in LANGUAGE_ALIASES

    def test_cin_aliases_include_common_names(self):
        """CIN_ALIASES contient les noms courants."""
        from app.services.contact.import_export import CIN_ALIASES

        assert "cin" in CIN_ALIASES


# =====================================================================
# Segmentation — STOP command
# =====================================================================


class TestSegmentation:
    """Tests du service de segmentation."""

    def test_stop_command_detection_exact(self):
        """Le mot 'STOP' est detecte comme commande STOP."""
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("STOP")

    def test_stop_command_detection_lowercase(self):
        """Le mot 'stop' en minuscules est detecte."""
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("stop")

    def test_stop_command_detection_with_spaces(self):
        """'  STOP  ' avec espaces est detecte."""
        from app.services.contact.segmentation import SegmentationService

        assert SegmentationService.is_stop_command("  STOP  ")

    def test_stop_command_not_substring(self):
        """'NONSTOP' n'est PAS une commande STOP."""
        from app.services.contact.segmentation import SegmentationService

        assert not SegmentationService.is_stop_command("NONSTOP")

    def test_stop_command_normal_message(self):
        """Un message normal n'est PAS une commande STOP."""
        from app.services.contact.segmentation import SegmentationService

        assert not SegmentationService.is_stop_command("Bonjour, comment ca va ?")
