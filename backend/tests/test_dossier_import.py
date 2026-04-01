"""Tests for DossierImportService — Wave 23B.

Covers sanitisation, phone normalisation, change detection,
Excel/CSV parsing, file validation, and statut mapping.
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from app.models.enums import DossierStatut
from app.services.dossier.import_service import (
    STATUT_MAPPING,
    DossierImportRow,
    DossierImportService,
)


@pytest.fixture
def import_service() -> DossierImportService:
    return DossierImportService()


# ── Sanitisation ─────────────────────────────────────────────────


class TestSanitizeRow:
    def test_strips_html(self, import_service: DossierImportService) -> None:
        row = DossierImportRow(
            row_number=1,
            raison_sociale="<script>alert('xss')</script>SARL Test",
        )
        sanitized = import_service.sanitize_row(row)
        assert "<script>" not in (sanitized.raison_sociale or "")
        assert "SARL Test" in (sanitized.raison_sociale or "")

    def test_strips_html_from_observations(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(
            row_number=1,
            observations="<b>Note</b> importante <img src=x>",
        )
        sanitized = import_service.sanitize_row(row)
        assert sanitized.observations == "Note importante"

    def test_detects_sql_injection(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(
            row_number=1,
            observations="'; DROP TABLE dossiers; --",
        )
        sanitized = import_service.sanitize_row(row)
        assert "DROP TABLE" not in (sanitized.observations or "")

    def test_detects_union_select(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(
            row_number=1,
            type_projet="test UNION SELECT * FROM admins",
        )
        sanitized = import_service.sanitize_row(row)
        assert "UNION SELECT" not in (sanitized.type_projet or "")

    def test_strips_whitespace(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(
            row_number=1,
            numero="  2024-001  ",
            region="  RSK  ",
        )
        sanitized = import_service.sanitize_row(row)
        assert sanitized.numero == "2024-001"
        assert sanitized.region == "RSK"

    def test_none_fields_stay_none(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, numero="2024-001")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.type_projet is None
        assert sanitized.region is None

    def test_empty_string_becomes_none(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, numero="X", region="   ")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.region is None


# ── Phone normalisation ──────────────────────────────────────────


class TestPhoneNormalisation:
    def test_local_06_format(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="0612345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_local_07_format(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="0712345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212712345678"

    def test_00212_format(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="00212612345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_keeps_valid_e164(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="+212612345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_strips_spaces_and_dashes(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="06 12 34 56 78")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_strips_dots(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="06.12.34.56.78")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_invalid_returns_none(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="123")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone is None

    def test_empty_returns_none(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone is None

    def test_212_without_plus(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="212612345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+212612345678"

    def test_non_moroccan_kept(
        self, import_service: DossierImportService,
    ) -> None:
        row = DossierImportRow(row_number=1, phone="+33612345678")
        sanitized = import_service.sanitize_row(row)
        assert sanitized.phone == "+33612345678"


# ── Change detection ─────────────────────────────────────────────


class TestDetectChanges:
    def test_finds_changed_fields(
        self, import_service: DossierImportService,
    ) -> None:
        existing = MagicMock()
        existing.statut = DossierStatut.en_attente
        existing.type_projet = "Industrie"
        existing.raison_sociale = "SARL Test"
        existing.montant_investissement = None
        existing.region = "RSK"
        existing.secteur = "Agro"
        existing.date_depot = None
        existing.observations = None

        new_data = DossierImportRow(
            row_number=1,
            numero="2024-001",
            statut="en_cours",
            type_projet="Industrie",
            raison_sociale="SARL Test Modifié",
        )
        changes = import_service.detect_changes(existing, new_data)
        field_names = [c.field_name for c in changes]
        assert "statut" in field_names
        assert "raison_sociale" in field_names
        assert "type_projet" not in field_names  # unchanged

    def test_ignores_none_in_new_data(
        self, import_service: DossierImportService,
    ) -> None:
        existing = MagicMock()
        existing.statut = DossierStatut.en_cours
        existing.type_projet = "Industrie"
        existing.raison_sociale = "SARL"
        existing.montant_investissement = Decimal("100000")
        existing.region = "RSK"
        existing.secteur = "Agro"
        existing.date_depot = None
        existing.observations = None

        new_data = DossierImportRow(row_number=1, numero="2024-001")
        changes = import_service.detect_changes(existing, new_data)
        assert len(changes) == 0

    def test_montant_change_detected(
        self, import_service: DossierImportService,
    ) -> None:
        existing = MagicMock()
        existing.statut = DossierStatut.en_attente
        existing.type_projet = None
        existing.raison_sociale = None
        existing.montant_investissement = Decimal("100000.00")
        existing.region = None
        existing.secteur = None
        existing.date_depot = None
        existing.observations = None

        new_data = DossierImportRow(
            row_number=1,
            numero="2024-001",
            montant_investissement="200000",
        )
        changes = import_service.detect_changes(existing, new_data)
        field_names = [c.field_name for c in changes]
        assert "montant_investissement" in field_names

    def test_no_change_returns_empty(
        self, import_service: DossierImportService,
    ) -> None:
        existing = MagicMock()
        existing.statut = DossierStatut.en_cours
        existing.type_projet = "Industrie"
        existing.raison_sociale = "SARL"
        existing.montant_investissement = None
        existing.region = None
        existing.secteur = None
        existing.date_depot = None
        existing.observations = None

        new_data = DossierImportRow(
            row_number=1,
            numero="2024-001",
            statut="en_cours",
            type_projet="Industrie",
            raison_sociale="SARL",
        )
        changes = import_service.detect_changes(existing, new_data)
        assert len(changes) == 0


# ── File extension validation ────────────────────────────────────


class TestFileValidation:
    def test_rejects_wrong_extension(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("report.exe") is False

    def test_rejects_pdf(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("data.pdf") is False

    def test_accepts_xlsx(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("dossiers.xlsx") is True

    def test_accepts_csv(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("dossiers.csv") is True

    def test_accepts_xls(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("data.xls") is True

    def test_case_insensitive(
        self, import_service: DossierImportService,
    ) -> None:
        assert import_service._check_extension("DATA.XLSX") is True


# ── Statut mapping ───────────────────────────────────────────────


class TestStatutMapping:
    def test_known_values(self) -> None:
        assert STATUT_MAPPING["en cours"] == DossierStatut.en_cours
        assert STATUT_MAPPING["en_cours"] == DossierStatut.en_cours
        assert STATUT_MAPPING["incomplet"] == DossierStatut.incomplet

    def test_accented_values(self) -> None:
        assert STATUT_MAPPING["validé"] == DossierStatut.valide
        assert STATUT_MAPPING["rejeté"] == DossierStatut.rejete
        assert STATUT_MAPPING["complément"] == DossierStatut.complement

    def test_unaccented_values(self) -> None:
        assert STATUT_MAPPING["valide"] == DossierStatut.valide
        assert STATUT_MAPPING["rejete"] == DossierStatut.rejete


# ── Excel parsing ────────────────────────────────────────────────


class TestParseExcel:
    def _make_xlsx(self, tmp_path, headers: list[str], rows: list[list]) -> str:
        """Create a temporary xlsx file for testing."""
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        path = str(tmp_path / "test.xlsx")
        wb.save(path)
        wb.close()
        return path

    def test_basic_parse(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        path = self._make_xlsx(
            tmp_path,
            ["Numéro", "Statut", "Raison Sociale", "Téléphone"],
            [
                ["2024-001", "en cours", "SARL Alpha", "0612345678"],
                ["2024-002", "validé", "SA Beta", "0712345678"],
            ],
        )
        rows = import_service.parse_excel(path)
        assert len(rows) == 2
        assert rows[0].numero == "2024-001"
        assert rows[0].statut == "en cours"
        assert rows[0].raison_sociale == "SARL Alpha"
        assert rows[0].phone == "0612345678"
        assert rows[1].numero == "2024-002"

    def test_column_mapping(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        path = self._make_xlsx(
            tmp_path,
            ["N° Dossier", "État", "Nom Entreprise"],
            [["2024-001", "en cours", "SARL Test"]],
        )
        mapping = {
            "N° Dossier": "numero",
            "État": "statut",
            "Nom Entreprise": "raison_sociale",
        }
        rows = import_service.parse_excel(path, column_mapping=mapping)
        assert len(rows) == 1
        assert rows[0].numero == "2024-001"
        assert rows[0].statut == "en cours"
        assert rows[0].raison_sociale == "SARL Test"

    def test_skips_empty_rows(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        path = self._make_xlsx(
            tmp_path,
            ["Numéro", "Statut"],
            [
                ["2024-001", "en cours"],
                [None, None],
                ["2024-002", "validé"],
            ],
        )
        rows = import_service.parse_excel(path)
        assert len(rows) == 2

    def test_preserves_raw_data(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        path = self._make_xlsx(
            tmp_path,
            ["Numéro", "Extra Column"],
            [["2024-001", "some extra data"]],
        )
        rows = import_service.parse_excel(path)
        assert len(rows) == 1
        assert "Extra Column" in rows[0].raw_data


# ── CSV parsing ──────────────────────────────────────────────────


class TestParseCsv:
    def _make_csv(self, tmp_path, content: str, encoding: str = "utf-8") -> str:
        """Create a temporary CSV file for testing."""
        path = str(tmp_path / "test.csv")
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(content)
        return path

    def test_basic_parse(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        csv_content = (
            "Numéro,Statut,Raison Sociale,Téléphone\n"
            "2024-001,en cours,SARL Alpha,0612345678\n"
            "2024-002,validé,SA Beta,0712345678\n"
        )
        path = self._make_csv(tmp_path, csv_content)
        rows = import_service.parse_csv(path)
        assert len(rows) == 2
        assert rows[0].numero == "2024-001"
        assert rows[0].statut == "en cours"
        assert rows[0].phone == "0612345678"

    def test_semicolon_separator(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        csv_content = (
            "Numéro;Statut;Raison Sociale\n"
            "2024-001;en cours;SARL Alpha\n"
        )
        path = self._make_csv(tmp_path, csv_content)
        rows = import_service.parse_csv(path)
        assert len(rows) == 1
        assert rows[0].numero == "2024-001"
        assert rows[0].raison_sociale == "SARL Alpha"

    def test_latin1_encoding(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        csv_content = "Numéro;Statut\n2024-001;validé\n"
        path = self._make_csv(tmp_path, csv_content, encoding="latin-1")
        rows = import_service.parse_csv(path)
        assert len(rows) == 1
        assert rows[0].statut == "validé"

    def test_empty_file_returns_empty(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        path = self._make_csv(tmp_path, "")
        rows = import_service.parse_csv(path)
        assert rows == []

    def test_skips_empty_rows(
        self, import_service: DossierImportService, tmp_path,
    ) -> None:
        csv_content = (
            "Numéro,Statut\n"
            "2024-001,en cours\n"
            ",\n"
            "2024-002,validé\n"
        )
        path = self._make_csv(tmp_path, csv_content)
        rows = import_service.parse_csv(path)
        assert len(rows) == 2
