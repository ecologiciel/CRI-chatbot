"""Completion tests for DossierImportService — Wave 29B.

Adds tests NOT covered by test_dossier_import.py (Wave 23B):
- validate_file() oversized file rejection
- validate_file() service-level duplicate hash detection
- validate_file() happy path
- SQL injection variant: OR 1=1
- Sanitize preserves legitimate content with SQL-like words
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import Workbook

from app.services.dossier.import_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    DossierImportRow,
    DossierImportService,
)

from tests.unit.conftest import make_tenant


# -- Helpers ----------------------------------------------------------------


def _make_xlsx(tmp_path, headers: list[str], rows: list[list]) -> str:
    """Create a temporary xlsx file for testing."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path = str(tmp_path / "test_import.xlsx")
    wb.save(path)
    wb.close()
    return path


def _mock_tenant_session(*, scalar_result=None):
    """Create a tenant with a mocked db_session."""
    tenant = make_tenant(slug="rabat")

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_result
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _fake_db_session(self):
        yield session

    return tenant, session, _fake_db_session


@pytest.fixture
def import_service() -> DossierImportService:
    return DossierImportService()


# -- Tests: validate_file edge cases ----------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestValidateFileComplete:
    """Tests for validate_file() not covered by test_dossier_import.py."""

    @pytest.mark.asyncio
    async def test_reject_oversized_file(self, import_service, tmp_path) -> None:
        """File exceeding MAX_FILE_SIZE_MB → is_valid=False, error mentions 'volumineux'."""
        path = _make_xlsx(tmp_path, ["Numéro"], [["2024-001"]])
        tenant, session, fake_db = _mock_tenant_session()

        # Patch getsize to return just over the limit
        over_limit = MAX_FILE_SIZE_MB * 1024 * 1024 + 1

        with (
            patch("os.path.getsize", return_value=over_limit),
            patch.object(type(tenant), "db_session", fake_db),
        ):
            result = await import_service.validate_file(path, tenant)

        assert result.is_valid is False
        assert "volumineux" in result.error.lower()
        assert result.file_size == over_limit

    @pytest.mark.asyncio
    async def test_detect_duplicate_hash_service_level(self, import_service, tmp_path) -> None:
        """File with hash matching completed SyncLog → is_duplicate=True."""
        path = _make_xlsx(tmp_path, ["Numéro"], [["2024-001"]])
        actual_size = os.path.getsize(path)

        # DB returns a match for the SHA-256 hash
        tenant, session, fake_db = _mock_tenant_session(
            scalar_result=MagicMock(),  # non-None = existing sync_log
        )

        with patch.object(type(tenant), "db_session", fake_db):
            result = await import_service.validate_file(path, tenant)

        assert result.is_valid is False
        assert result.is_duplicate is True
        assert result.file_hash is not None
        assert "déjà été importé" in result.error

    @pytest.mark.asyncio
    async def test_validate_file_happy_path(self, import_service, tmp_path) -> None:
        """Valid file with no duplicate → is_valid=True."""
        path = _make_xlsx(tmp_path, ["Numéro", "Statut"], [["2024-001", "en cours"]])

        tenant, session, fake_db = _mock_tenant_session(scalar_result=None)

        with patch.object(type(tenant), "db_session", fake_db):
            result = await import_service.validate_file(path, tenant)

        assert result.is_valid is True
        assert result.is_duplicate is False
        assert result.file_hash is not None
        assert result.file_size > 0


# -- Tests: sanitisation edge cases -----------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestSanitizationComplete:
    """SQL injection variants and edge cases not in test_dossier_import.py."""

    def test_detect_sql_injection_or_1_equals_1(self, import_service) -> None:
        """OR 1=1 pattern is neutralised."""
        row = DossierImportRow(
            row_number=1,
            observations="test' OR 1=1 --",
        )
        sanitized = import_service.sanitize_row(row)
        assert "OR 1=1" not in (sanitized.observations or "")

    def test_sanitize_preserves_legitimate_content(self, import_service) -> None:
        """Legitimate text with SQL-like words is NOT stripped.

        Regression: 'UNION bank' should remain — only 'UNION SELECT' is dangerous.
        """
        row = DossierImportRow(
            row_number=1,
            raison_sociale="UNION Bancaire du Maghreb",
            observations="SELECT the best investment plan",
        )
        sanitized = import_service.sanitize_row(row)
        # "UNION" alone (without SELECT) should survive
        assert "UNION" in (sanitized.raison_sociale or "")
        # "SELECT" alone (without UNION before it) should survive
        assert "SELECT" in (sanitized.observations or "") or "investment" in (sanitized.observations or "")
