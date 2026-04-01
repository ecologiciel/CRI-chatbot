"""Tests for Phase 3 data models: Dossier, DossierHistory, SyncLog, SyncConfig.

Verifies model imports, enum values, schema validation, and from_attributes
compatibility.  These tests are import-only (no DB required).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.dossier import Dossier, DossierHistory
from app.models.enums import (
    DossierStatut,
    SyncProviderType,
    SyncSourceType,
    SyncStatus,
)
from app.models.sync import SyncConfig, SyncLog
from app.schemas.dossier import (
    DossierCreate,
    DossierDetail,
    DossierFilters,
    DossierHistoryRead,
    DossierList,
    DossierRead,
    DossierStats,
)
from app.schemas.sync import (
    ImportReportResponse,
    ImportTriggerRequest,
    SyncConfigCreate,
    SyncConfigRead,
    SyncConfigUpdate,
    SyncLogList,
    SyncLogRead,
)


# ── Model import tests ───────────────────────────────────────────


class TestDossierModel:
    def test_tablename(self):
        assert Dossier.__tablename__ == "dossiers"

    def test_columns_exist(self):
        assert hasattr(Dossier, "numero")
        assert hasattr(Dossier, "statut")
        assert hasattr(Dossier, "contact_id")
        assert hasattr(Dossier, "type_projet")
        assert hasattr(Dossier, "raison_sociale")
        assert hasattr(Dossier, "montant_investissement")
        assert hasattr(Dossier, "region")
        assert hasattr(Dossier, "secteur")
        assert hasattr(Dossier, "date_depot")
        assert hasattr(Dossier, "date_derniere_maj")
        assert hasattr(Dossier, "observations")
        assert hasattr(Dossier, "raw_data")
        assert hasattr(Dossier, "created_at")
        assert hasattr(Dossier, "updated_at")


class TestDossierHistoryModel:
    def test_tablename(self):
        assert DossierHistory.__tablename__ == "dossier_history"

    def test_columns_exist(self):
        assert hasattr(DossierHistory, "dossier_id")
        assert hasattr(DossierHistory, "field_changed")
        assert hasattr(DossierHistory, "old_value")
        assert hasattr(DossierHistory, "new_value")
        assert hasattr(DossierHistory, "changed_at")
        assert hasattr(DossierHistory, "sync_log_id")


class TestSyncLogModel:
    def test_tablename(self):
        assert SyncLog.__tablename__ == "sync_logs"

    def test_columns_exist(self):
        assert hasattr(SyncLog, "source_type")
        assert hasattr(SyncLog, "file_name")
        assert hasattr(SyncLog, "file_hash")
        assert hasattr(SyncLog, "rows_total")
        assert hasattr(SyncLog, "rows_imported")
        assert hasattr(SyncLog, "rows_updated")
        assert hasattr(SyncLog, "rows_errored")
        assert hasattr(SyncLog, "error_details")
        assert hasattr(SyncLog, "status")
        assert hasattr(SyncLog, "started_at")
        assert hasattr(SyncLog, "completed_at")
        assert hasattr(SyncLog, "triggered_by")
        assert hasattr(SyncLog, "created_at")


class TestSyncConfigModel:
    def test_tablename(self):
        assert SyncConfig.__tablename__ == "sync_configs"

    def test_columns_exist(self):
        assert hasattr(SyncConfig, "provider_type")
        assert hasattr(SyncConfig, "config_json")
        assert hasattr(SyncConfig, "column_mapping")
        assert hasattr(SyncConfig, "schedule_cron")
        assert hasattr(SyncConfig, "watched_folder")
        assert hasattr(SyncConfig, "is_active")
        assert hasattr(SyncConfig, "created_at")
        assert hasattr(SyncConfig, "updated_at")


# ── Enum tests ───────────────────────────────────────────────────


class TestEnums:
    def test_dossier_statut_values(self):
        assert DossierStatut.en_cours.value == "en_cours"
        assert DossierStatut.valide.value == "valide"
        assert DossierStatut.rejete.value == "rejete"
        assert DossierStatut.en_attente.value == "en_attente"
        assert DossierStatut.complement.value == "complement"
        assert DossierStatut.incomplet.value == "incomplet"

    def test_dossier_statut_count(self):
        assert len(DossierStatut) == 6

    def test_sync_status_values(self):
        assert SyncStatus.pending.value == "pending"
        assert SyncStatus.running.value == "running"
        assert SyncStatus.completed.value == "completed"
        assert SyncStatus.failed.value == "failed"

    def test_sync_status_count(self):
        assert len(SyncStatus) == 4

    def test_sync_source_type_values(self):
        assert SyncSourceType.excel.value == "excel"
        assert SyncSourceType.csv.value == "csv"
        assert SyncSourceType.api_rest.value == "api_rest"
        assert SyncSourceType.manual.value == "manual"

    def test_sync_source_type_count(self):
        assert len(SyncSourceType) == 4

    def test_sync_provider_type_values(self):
        assert SyncProviderType.excel_csv.value == "excel_csv"
        assert SyncProviderType.api_rest.value == "api_rest"
        assert SyncProviderType.db_link.value == "db_link"

    def test_sync_provider_type_count(self):
        assert len(SyncProviderType) == 3


# ── Schema validation tests ──────────────────────────────────────


class TestDossierSchemas:
    def test_dossier_create_minimal(self):
        d = DossierCreate(numero="2024-0001")
        assert d.numero == "2024-0001"
        assert d.statut == DossierStatut.en_attente
        assert d.contact_id is None
        assert d.montant_investissement is None

    def test_dossier_create_full(self):
        d = DossierCreate(
            numero="2024-0002",
            statut=DossierStatut.en_cours,
            type_projet="Industrie",
            raison_sociale="SARL Test",
            montant_investissement=Decimal("1500000.00"),
            region="Rabat-Salé-Kénitra",
            secteur="Agroalimentaire",
            date_depot=date(2024, 3, 15),
            observations="Dossier prioritaire",
        )
        assert d.montant_investissement == Decimal("1500000.00")
        assert d.region == "Rabat-Salé-Kénitra"

    def test_dossier_create_negative_montant_rejected(self):
        with pytest.raises(Exception):
            DossierCreate(
                numero="2024-0003",
                montant_investissement=Decimal("-100"),
            )

    def test_dossier_read_from_dict(self):
        data = {
            "id": uuid.uuid4(),
            "numero": "2024-0001",
            "contact_id": None,
            "statut": DossierStatut.en_cours,
            "type_projet": "Industrie",
            "raison_sociale": "SARL Test",
            "montant_investissement": None,
            "region": "Rabat-Salé-Kénitra",
            "secteur": "Agroalimentaire",
            "date_depot": None,
            "date_derniere_maj": None,
            "observations": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        d = DossierRead(**data)
        assert d.numero == "2024-0001"
        assert d.statut == DossierStatut.en_cours

    def test_dossier_detail_with_history(self):
        now = datetime.now()
        d = DossierDetail(
            id=uuid.uuid4(),
            numero="2024-0001",
            contact_id=None,
            statut=DossierStatut.valide,
            type_projet=None,
            raison_sociale=None,
            montant_investissement=None,
            region=None,
            secteur=None,
            date_depot=None,
            date_derniere_maj=None,
            observations=None,
            created_at=now,
            updated_at=now,
            history=[
                DossierHistoryRead(
                    id=uuid.uuid4(),
                    field_changed="statut",
                    old_value="en_attente",
                    new_value="valide",
                    changed_at=now,
                    sync_log_id=None,
                ),
            ],
        )
        assert len(d.history) == 1
        assert d.history[0].field_changed == "statut"

    def test_dossier_list(self):
        dl = DossierList(items=[], total=0, page=1, page_size=20)
        assert dl.total == 0

    def test_dossier_stats(self):
        ds = DossierStats(total=100, en_cours=30, valide=50, en_attente=20)
        assert ds.total == 100
        assert ds.rejete == 0

    def test_dossier_filters_empty(self):
        f = DossierFilters()
        assert f.statut is None
        assert f.search is None

    def test_dossier_filters_with_values(self):
        f = DossierFilters(
            statut=DossierStatut.en_cours,
            search="SARL",
            date_depot_from=date(2024, 1, 1),
        )
        assert f.statut == DossierStatut.en_cours
        assert f.search == "SARL"


class TestSyncSchemas:
    def test_sync_log_read(self):
        data = {
            "id": uuid.uuid4(),
            "source_type": SyncSourceType.excel,
            "file_name": "dossiers_2024.xlsx",
            "file_hash": "a" * 64,
            "rows_total": 100,
            "rows_imported": 90,
            "rows_updated": 5,
            "rows_errored": 5,
            "error_details": {"row_12": "invalid CIN"},
            "status": SyncStatus.completed,
            "started_at": datetime.now(),
            "completed_at": datetime.now(),
            "triggered_by": uuid.uuid4(),
            "created_at": datetime.now(),
        }
        sl = SyncLogRead(**data)
        assert sl.rows_total == 100
        assert sl.status == SyncStatus.completed

    def test_sync_log_list(self):
        sll = SyncLogList(items=[], total=0, page=1, page_size=20)
        assert sll.total == 0

    def test_sync_config_create_with_mapping(self):
        sc = SyncConfigCreate(
            column_mapping={
                "N° Dossier": "numero",
                "Statut": "statut",
                "Raison Sociale": "raison_sociale",
            },
            schedule_cron="0 6 * * *",
        )
        assert sc.column_mapping["N° Dossier"] == "numero"
        assert sc.provider_type == SyncProviderType.excel_csv
        assert sc.is_active is True

    def test_sync_config_create_invalid_cron_rejected(self):
        with pytest.raises(Exception):
            SyncConfigCreate(
                column_mapping={"col": "field"},
                schedule_cron="not a cron",
            )

    def test_sync_config_update_partial(self):
        su = SyncConfigUpdate(is_active=False)
        assert su.is_active is False
        assert su.column_mapping is None

    def test_sync_config_read(self):
        now = datetime.now()
        sc = SyncConfigRead(
            id=uuid.uuid4(),
            provider_type=SyncProviderType.excel_csv,
            config_json={},
            column_mapping={"col": "field"},
            schedule_cron=None,
            watched_folder=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert sc.is_active is True

    def test_import_trigger_request(self):
        it = ImportTriggerRequest(file_path="imports/dossiers_2024.xlsx")
        assert it.file_path == "imports/dossiers_2024.xlsx"
        assert it.sync_config_id is None

    def test_import_report_response(self):
        ir = ImportReportResponse(
            sync_log_id=uuid.uuid4(),
            status=SyncStatus.completed,
            rows_total=100,
            rows_imported=95,
            rows_updated=3,
            rows_errored=2,
            duration_seconds=12.5,
        )
        assert ir.rows_total == 100
        assert ir.duration_seconds == 12.5
