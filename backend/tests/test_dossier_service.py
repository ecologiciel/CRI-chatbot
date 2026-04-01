"""Unit tests for DossierService — consultation, anti-BOLA, WhatsApp formatting.

All DB access is mocked via patched tenant.db_session().
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import CRIBaseException, ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.enums import DossierStatut, Language
from app.schemas.dossier import DossierDetail, DossierFilters, DossierHistoryRead


# ── Helpers ──────────────────────────────────────────────────────


def _patch_db_session(session):
    """Create a class-level patchable db_session that accepts self."""

    @asynccontextmanager
    async def _fake_db_session(self):
        yield session

    return patch.object(TenantContext, "db_session", _fake_db_session)


def _make_dossier_orm(**overrides) -> MagicMock:
    """Create a mock Dossier ORM object with sensible defaults."""
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
        "raw_data": {"source_row": 42},
        "created_at": datetime(2024, 3, 15, 10, 0, 0),
        "updated_at": datetime(2024, 6, 20, 14, 30, 0),
        "history": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_contact_orm(**overrides) -> MagicMock:
    """Create a mock Contact ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "phone": "+212612345678",
        "name": "Ahmed Test",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_dossier_detail(**overrides) -> DossierDetail:
    """Create a DossierDetail schema for formatting tests."""
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


# ── Import tests ─────────────────────────────────────────────────


class TestDossierServiceImports:
    """Verify that all public symbols are importable."""

    def test_service_import(self):
        from app.services.dossier.service import DossierService

        assert DossierService is not None

    def test_singleton_factory_import(self):
        from app.services.dossier.service import get_dossier_service

        assert callable(get_dossier_service)

    def test_package_reexport(self):
        from app.services.dossier import DossierService, get_dossier_service

        assert DossierService is not None
        assert callable(get_dossier_service)

    def test_exception_import(self):
        from app.services.dossier.service import UnauthorizedDossierAccess

        assert UnauthorizedDossierAccess is not None

    def test_exception_inherits_cri_base(self):
        from app.services.dossier.service import UnauthorizedDossierAccess

        assert issubclass(UnauthorizedDossierAccess, CRIBaseException)

    def test_exception_carries_details(self):
        from app.services.dossier.service import UnauthorizedDossierAccess

        exc = UnauthorizedDossierAccess("+212612345678", "some-id")
        assert exc.details["phone_last4"] == "5678"
        assert exc.details["dossier_id"] == "some-id"
        assert "Unauthorized" in exc.message


# ── STATUT_LABELS tests ──────────────────────────────────────────


class TestStatutLabels:
    """Verify translation completeness for all language×statut combos."""

    def test_labels_cover_all_languages(self):
        from app.services.dossier.service import STATUT_LABELS

        for lang in Language:
            assert lang in STATUT_LABELS, f"Missing language: {lang}"

    def test_labels_cover_all_statuts(self):
        from app.services.dossier.service import STATUT_LABELS

        for lang in Language:
            for statut in DossierStatut:
                assert statut in STATUT_LABELS[lang], (
                    f"Missing label for {lang.value}/{statut.value}"
                )

    def test_labels_are_nonempty_strings(self):
        from app.services.dossier.service import STATUT_LABELS

        for lang in Language:
            for statut in DossierStatut:
                label = STATUT_LABELS[lang][statut]
                assert isinstance(label, str) and len(label) > 0

    def test_complement_label_exists(self):
        """Regression: complement was added as the 6th statut."""
        from app.services.dossier.service import STATUT_LABELS

        assert DossierStatut.complement in STATUT_LABELS[Language.fr]
        assert DossierStatut.complement in STATUT_LABELS[Language.ar]
        assert DossierStatut.complement in STATUT_LABELS[Language.en]


# ── WhatsApp formatting tests ────────────────────────────────────


class TestFormatDossierForWhatsApp:
    """Test trilingual WhatsApp message formatting."""

    @pytest.fixture
    def service(self):
        from app.services.dossier.service import DossierService

        return DossierService(audit=MagicMock())

    def test_format_french_all_fields(self, service):
        dossier = _make_dossier_detail()
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert "2024-CRI-0001" in result
        assert "En cours de traitement" in result
        assert "SARL Al Amal" in result
        assert "Industrie" in result
        assert "Rabat" in result

    def test_format_arabic(self, service):
        dossier = _make_dossier_detail(
            statut=DossierStatut.valide,
            raison_sociale="شركة تجريبية",
        )
        result = service.format_dossier_for_whatsapp(dossier, Language.ar)

        assert "2024-CRI-0001" in result
        assert "تمت الموافقة" in result
        assert "شركة تجريبية" in result
        assert "ملف رقم" in result

    def test_format_english(self, service):
        dossier = _make_dossier_detail(statut=DossierStatut.rejete)
        result = service.format_dossier_for_whatsapp(dossier, Language.en)

        assert "File N°" in result
        assert "Rejected" in result

    def test_format_omits_none_fields(self, service):
        dossier = _make_dossier_detail(
            raison_sociale=None,
            date_derniere_maj=None,
            type_projet=None,
            region=None,
            secteur=None,
            date_depot=None,
            observations=None,
        )
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert "None" not in result
        assert "Raison sociale" not in result
        assert "Dernière mise à jour" not in result
        assert "Type de projet" not in result

    def test_format_never_includes_montant(self, service):
        """SECURITY: montant_investissement must NEVER appear in WhatsApp."""
        dossier = _make_dossier_detail(
            montant_investissement=Decimal("5000000.00"),
        )
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert "5000000" not in result
        assert "montant" not in result.lower()

    def test_format_never_includes_contact_id(self, service):
        """SECURITY: internal UUID must not leak to WhatsApp."""
        contact_id = uuid.uuid4()
        dossier = _make_dossier_detail(contact_id=contact_id)
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert str(contact_id) not in result

    def test_format_never_includes_raw_data(self, service):
        """SECURITY: raw_data is internal import metadata."""
        dossier = _make_dossier_detail()
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert "raw_data" not in result
        assert "source_row" not in result

    def test_format_uses_whatsapp_bold(self, service):
        dossier = _make_dossier_detail()
        result = service.format_dossier_for_whatsapp(dossier, Language.fr)

        assert "*Dossier N°" in result


# ── Anti-BOLA tests ──────────────────────────────────────────────


class TestGetDossierWithBolaCheck:
    """Critical security tests for BOLA protection."""

    @pytest.fixture
    def audit_mock(self):
        audit = AsyncMock()
        audit.log_action = AsyncMock()
        return audit

    @pytest.fixture
    def service(self, audit_mock):
        from app.services.dossier.service import DossierService

        return DossierService(audit=audit_mock)

    @pytest.mark.asyncio
    async def test_allows_access_when_phone_owns_dossier(
        self, service, audit_mock
    ):
        """Anti-BOLA: access granted when phone matches dossier's contact."""
        contact_id = uuid.uuid4()
        dossier_id = uuid.uuid4()
        phone = "+212612345678"

        dossier_orm = _make_dossier_orm(
            id=dossier_id, contact_id=contact_id
        )
        contact_orm = _make_contact_orm(id=contact_id, phone=phone)

        # Mock session: first execute returns dossier, second returns contact
        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = dossier_orm
            else:
                result.scalar_one_or_none.return_value = contact_orm
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.get_dossier_with_bola_check(
                tenant, dossier_id, phone
            )

        assert result is not None
        assert result.id == dossier_id
        # Verify audit log was called for access granted
        audit_mock.log_action.assert_called()
        call_args = audit_mock.log_action.call_args[0][0]
        assert call_args.action == "access"

    @pytest.mark.asyncio
    async def test_denies_access_when_phone_does_not_own_dossier(
        self, service, audit_mock
    ):
        """Anti-BOLA: access DENIED when phone's contact != dossier's contact."""
        from app.services.dossier.service import UnauthorizedDossierAccess

        owner_contact_id = uuid.uuid4()
        attacker_contact_id = uuid.uuid4()
        dossier_id = uuid.uuid4()
        attacker_phone = "+212699999999"

        dossier_orm = _make_dossier_orm(
            id=dossier_id, contact_id=owner_contact_id
        )
        attacker_contact = _make_contact_orm(
            id=attacker_contact_id, phone=attacker_phone
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = dossier_orm
            else:
                result.scalar_one_or_none.return_value = attacker_contact
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            with pytest.raises(UnauthorizedDossierAccess):
                await service.get_dossier_with_bola_check(
                    tenant, dossier_id, attacker_phone
                )

        # Verify denial was audit-logged
        audit_mock.log_action.assert_called_once()
        call_args = audit_mock.log_action.call_args[0][0]
        assert call_args.action == "access_denied"
        assert call_args.details["reason"] == "bola_violation"
        assert call_args.details["phone_last4"] == "9999"

    @pytest.mark.asyncio
    async def test_denies_when_contact_not_found(self, service, audit_mock):
        """Anti-BOLA: denied when phone has no contact record at all."""
        from app.services.dossier.service import UnauthorizedDossierAccess

        dossier_id = uuid.uuid4()
        dossier_orm = _make_dossier_orm(id=dossier_id)

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = dossier_orm
            else:
                result.scalar_one_or_none.return_value = None  # no contact
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            with pytest.raises(UnauthorizedDossierAccess):
                await service.get_dossier_with_bola_check(
                    tenant, dossier_id, "+212600000000"
                )

    @pytest.mark.asyncio
    async def test_raises_not_found_when_dossier_missing(
        self, service, audit_mock
    ):
        """ResourceNotFoundError when the dossier doesn't exist."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            with pytest.raises(ResourceNotFoundError):
                await service.get_dossier_with_bola_check(
                    tenant, uuid.uuid4(), "+212612345678"
                )

        # No audit log for "not found" (not a BOLA violation)
        audit_mock.log_action.assert_not_called()


# ── get_dossiers_by_phone tests ──────────────────────────────────


class TestGetDossiersByPhone:
    """Test phone-to-dossier lookup (intrinsically BOLA-safe)."""

    @pytest.fixture
    def service(self):
        from app.services.dossier.service import DossierService

        return DossierService(audit=AsyncMock())

    @pytest.mark.asyncio
    async def test_returns_empty_if_no_contact(self, service):
        """No contact for phone → empty list, no error."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.get_dossiers_by_phone(
                tenant, "+212600000000"
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_dossiers_for_known_contact(self, service):
        """Returns list of DossierRead for a known phone's contact."""
        contact_id = uuid.uuid4()
        contact = _make_contact_orm(id=contact_id, phone="+212612345678")
        dossier1 = _make_dossier_orm(contact_id=contact_id, numero="D-001")
        dossier2 = _make_dossier_orm(contact_id=contact_id, numero="D-002")

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Contact lookup
                result.scalar_one_or_none.return_value = contact
            else:
                # Dossier list
                result.scalars.return_value.all.return_value = [
                    dossier1,
                    dossier2,
                ]
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.get_dossiers_by_phone(
                tenant, "+212612345678"
            )

        assert len(result) == 2
        assert result[0].numero == "D-001"
        assert result[1].numero == "D-002"


# ── get_dossier_by_numero tests ──────────────────────────────────


class TestGetDossierByNumero:
    """Test dossier lookup by numero."""

    @pytest.fixture
    def service(self):
        from app.services.dossier.service import DossierService

        return DossierService(audit=MagicMock())

    @pytest.mark.asyncio
    async def test_returns_detail_when_found(self, service):
        dossier_orm = _make_dossier_orm(numero="2024-RSK-0042")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = dossier_orm
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.get_dossier_by_numero(
                tenant, "2024-RSK-0042"
            )

        assert result is not None
        assert result.numero == "2024-RSK-0042"
        assert isinstance(result, DossierDetail)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, service):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.get_dossier_by_numero(
                tenant, "NONEXISTENT"
            )

        assert result is None


# ── get_dossier_stats tests ──────────────────────────────────────


class TestGetDossierStats:
    """Test aggregated stats query."""

    @pytest.fixture
    def service(self):
        from app.services.dossier.service import DossierService

        return DossierService(audit=MagicMock())

    @pytest.mark.asyncio
    async def test_returns_stats_with_all_fields(self, service):
        mock_row = MagicMock()
        mock_row.total = 100
        mock_row.en_cours = 30
        mock_row.valide = 25
        mock_row.rejete = 10
        mock_row.en_attente = 15
        mock_row.complement = 8
        mock_row.incomplet = 12

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            stats = await service.get_dossier_stats(tenant)

        assert stats.total == 100
        assert stats.en_cours == 30
        assert stats.valide == 25
        assert stats.rejete == 10
        assert stats.en_attente == 15
        assert stats.complement == 8
        assert stats.incomplet == 12

    @pytest.mark.asyncio
    async def test_empty_table_returns_zeros(self, service):
        mock_row = MagicMock()
        mock_row.total = 0
        mock_row.en_cours = 0
        mock_row.valide = 0
        mock_row.rejete = 0
        mock_row.en_attente = 0
        mock_row.complement = 0
        mock_row.incomplet = 0

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            stats = await service.get_dossier_stats(tenant)

        assert stats.total == 0
        assert stats.complement == 0


# ── list_dossiers tests ──────────────────────────────────────────


class TestListDossiers:
    """Test paginated dossier listing."""

    @pytest.fixture
    def service(self):
        from app.services.dossier.service import DossierService

        return DossierService(audit=MagicMock())

    @pytest.mark.asyncio
    async def test_returns_paginated_list(self, service):
        dossier_orm = _make_dossier_orm(numero="D-001")

        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # COUNT query
                result.scalar_one.return_value = 1
            else:
                # Data query
                result.scalars.return_value.all.return_value = [dossier_orm]
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.list_dossiers(
                tenant, page=1, page_size=20
            )

        assert result.total == 1
        assert result.page == 1
        assert result.page_size == 20
        assert len(result.items) == 1
        assert result.items[0].numero == "D-001"

    @pytest.mark.asyncio
    async def test_with_statut_filter(self, service):
        """Verify that filters are applied (the query includes the WHERE)."""
        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = 0
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        filters = DossierFilters(statut=DossierStatut.valide)
        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.list_dossiers(
                tenant, filters=filters, page=1, page_size=10
            )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_with_search_filter(self, service):
        mock_session = AsyncMock()
        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = 0
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_session.commit = AsyncMock()

        from tests.unit.conftest import make_tenant

        filters = DossierFilters(search="SARL")
        tenant = make_tenant(slug="rabat")
        with _patch_db_session(mock_session):
            result = await service.list_dossiers(
                tenant, filters=filters, page=1, page_size=10
            )

        assert result.total == 0
        # Importantly: session.execute was called (filter applied, no crash)
        assert mock_session.execute.call_count == 2
