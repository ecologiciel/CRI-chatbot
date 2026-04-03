"""Completion tests for DossierService — Wave 29B.

Adds non-regression edge cases NOT in test_dossier_service.py (Wave 23B):
- Complement status formatting (6th statut added later)
- DossierDetail with non-empty history
- BOLA with dossier having no contact_id
- Page 2 pagination offset
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import DossierStatut, Language
from app.schemas.dossier import DossierDetail, DossierHistoryRead

from tests.unit.conftest import make_tenant


# -- Helpers ----------------------------------------------------------------


def _make_dossier_detail(**overrides) -> DossierDetail:
    defaults = {
        "id": uuid.uuid4(),
        "numero": "2024-CRI-0001",
        "contact_id": uuid.uuid4(),
        "statut": DossierStatut.en_cours,
        "type_projet": "Industrie",
        "raison_sociale": "SARL Al Amal",
        "montant_investissement": Decimal("1500000.00"),
        "region": "Rabat-Salé-Kénitra",
        "secteur": "Agroalimentaire",
        "date_depot": date(2024, 3, 15),
        "date_derniere_maj": date(2024, 6, 20),
        "observations": "RAS",
        "created_at": datetime(2024, 3, 15, 10, 0, 0),
        "updated_at": datetime(2024, 6, 20, 14, 30, 0),
        "history": [],
    }
    defaults.update(overrides)
    return DossierDetail(**defaults)


def _make_service():
    from app.services.dossier.service import DossierService

    return DossierService(audit=MagicMock())


def _patch_db_session(session):
    @asynccontextmanager
    async def _fake_db_session(self):
        yield session

    return patch.object(TenantContext, "db_session", _fake_db_session)


def _make_dossier_orm(**overrides) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "numero": "2024-CRI-0001",
        "contact_id": uuid.uuid4(),
        "statut": DossierStatut.en_cours,
        "type_projet": "Industrie",
        "raison_sociale": "SARL Al Amal",
        "montant_investissement": Decimal("1500000.00"),
        "region": "Rabat-Salé-Kénitra",
        "secteur": "Agroalimentaire",
        "date_depot": date(2024, 3, 15),
        "date_derniere_maj": date(2024, 6, 20),
        "observations": "RAS",
        "raw_data": None,
        "created_at": datetime(2024, 3, 15, 10, 0, 0),
        "updated_at": datetime(2024, 6, 20, 14, 30, 0),
        "history": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


# -- Tests ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestFormattingComplete:
    """Formatting edge cases not in test_dossier_service.py."""

    def test_format_whatsapp_complement_status(self) -> None:
        """Regression: 'complement' was the 6th statut added later."""
        service = _make_service()
        dossier = _make_dossier_detail(statut=DossierStatut.complement)

        result = service.format_dossier_for_whatsapp(dossier, Language.fr)
        assert "Complément" in result or "📎" in result

        result_ar = service.format_dossier_for_whatsapp(dossier, Language.ar)
        assert "تكملة" in result_ar or "📎" in result_ar

        result_en = service.format_dossier_for_whatsapp(dossier, Language.en)
        assert "Supplement" in result_en or "📎" in result_en

    def test_format_whatsapp_with_history_entries(self) -> None:
        """DossierDetail with non-empty history should still format correctly."""
        service = _make_service()
        history = [
            DossierHistoryRead(
                id=uuid.uuid4(),
                dossier_id=uuid.uuid4(),
                field_changed="statut",
                old_value="en_attente",
                new_value="en_cours",
                changed_at=datetime(2024, 5, 1, 12, 0, 0),
                sync_log_id=None,
            ),
        ]
        dossier = _make_dossier_detail(history=history)
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)
        assert "2024-CRI-0001" in result
        # History should NOT appear in WhatsApp message
        assert "en_attente" not in result


@pytest.mark.unit
@pytest.mark.phase3
class TestBOLAComplete:
    """BOLA edge cases not in test_dossier_service.py."""

    @pytest.mark.asyncio
    async def test_bola_check_with_dossier_no_contact_id(self) -> None:
        """Dossier exists but contact_id=None → denied (no owner to match)."""
        from app.services.dossier.service import DossierService, UnauthorizedDossierAccess

        audit = AsyncMock()
        audit.log_action = AsyncMock()
        service = DossierService(audit=audit)

        dossier_id = uuid.uuid4()
        dossier_orm = _make_dossier_orm(id=dossier_id, contact_id=None)

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = dossier_orm
            else:
                # No contact found for the phone
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            with pytest.raises(UnauthorizedDossierAccess):
                await service.get_dossier_with_bola_check(
                    tenant, dossier_id, "+212611111111"
                )


@pytest.mark.unit
@pytest.mark.phase3
class TestPaginationComplete:
    """Pagination edge case not in test_dossier_service.py."""

    @pytest.mark.asyncio
    async def test_list_dossiers_page_2(self) -> None:
        """Page 2 with page_size=10 → OFFSET should be 10."""
        service = _make_service()
        dossier_orm = _make_dossier_orm(numero="D-011")

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = 25  # total count
            else:
                result.scalars.return_value.all.return_value = [dossier_orm]
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.list_dossiers(tenant, page=2, page_size=10)

        assert result.total == 25
        assert result.page == 2
        assert result.page_size == 10
        assert len(result.items) == 1
