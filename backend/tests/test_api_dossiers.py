"""Tests for Dossier API endpoints (/api/v1/dossiers/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched TenantResolver for middleware bypass.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import (
    AdminRole,
    DossierStatut,
    SyncProviderType,
    SyncSourceType,
    SyncStatus,
)
from app.schemas.auth import AdminTokenPayload
from app.schemas.dossier import DossierList, DossierStats

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_admin_payload(role: str = AdminRole.admin_tenant.value, **overrides) -> AdminTokenPayload:
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": role,
        "tenant_id": str(TEST_TENANT.id),
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_dossier_orm(dossier_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock Dossier ORM object."""
    defaults = {
        "id": dossier_id or uuid.uuid4(),
        "numero": "RC-2025-001",
        "contact_id": uuid.uuid4(),
        "statut": DossierStatut.en_cours,
        "type_projet": "Création",
        "raison_sociale": "Test SARL",
        "montant_investissement": Decimal("500000.00"),
        "region": "Rabat-Salé-Kénitra",
        "secteur": "Industrie",
        "date_depot": date(2025, 3, 15),
        "date_derniere_maj": date(2025, 6, 1),
        "observations": None,
        "created_at": datetime(2025, 3, 15, tzinfo=UTC),
        "updated_at": datetime(2025, 6, 1, tzinfo=UTC),
        "history": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_sync_log_orm(log_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock SyncLog ORM object."""
    defaults = {
        "id": log_id or uuid.uuid4(),
        "source_type": SyncSourceType.excel,
        "file_name": "dossiers_2025.xlsx",
        "file_hash": "abc123def456",
        "rows_total": 100,
        "rows_imported": 90,
        "rows_updated": 5,
        "rows_errored": 5,
        "error_details": None,
        "status": SyncStatus.completed,
        "started_at": datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
        "completed_at": datetime(2025, 6, 1, 10, 5, tzinfo=UTC),
        "triggered_by": uuid.uuid4(),
        "created_at": datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_sync_config_orm(config_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock SyncConfig ORM object."""
    defaults = {
        "id": config_id or uuid.uuid4(),
        "provider_type": SyncProviderType.excel_csv,
        "config_json": {},
        "column_mapping": {"N° Dossier": "numero", "Statut": "statut"},
        "schedule_cron": "0 6 * * *",
        "watched_folder": None,
        "is_active": True,
        "created_at": datetime(2025, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2025, 6, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_tenant_db_session(
    *,
    scalar_one_or_none=None,
    scalars_all=None,
    execute_side_effect=None,
):
    """Create a mock for tenant.db_session() async context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    if execute_side_effect is not None:
        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = scalar_one_or_none

        if scalars_all is not None:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = scalars_all
            mock_result.scalars.return_value = mock_scalars

        mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session.get = AsyncMock(return_value=scalar_one_or_none)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    return mock_session


def _setup_overrides(role: str = AdminRole.admin_tenant.value) -> AdminTokenPayload:
    """Set RBAC dependency override and return admin payload."""
    payload = _make_admin_payload(role=role)
    app.dependency_overrides[get_current_admin] = lambda: payload
    return payload


def _clear_overrides():
    app.dependency_overrides.pop(get_current_admin, None)


def _headers() -> dict:
    return {
        "Authorization": "Bearer mock-token",
        "X-Tenant-ID": str(TEST_TENANT.id),
    }


# ---------------------------------------------------------------------------
# List dossiers
# ---------------------------------------------------------------------------


class TestListDossiers:
    @pytest.mark.asyncio
    async def test_list_success(self):
        """GET /dossiers returns paginated list."""
        _setup_overrides()
        dossier_list = DossierList(
            items=[], total=0, page=1, page_size=20
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dossiers.get_dossier_service"
                ) as mock_svc_factory,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                mock_svc = MagicMock()
                mock_svc.list_dossiers = AsyncMock(return_value=dossier_list)
                mock_svc_factory.return_value = mock_svc

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers?page=1&page_size=10",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_with_filters(self):
        """GET /dossiers?statut=en_cours passes filters to service."""
        _setup_overrides()
        dossier_list = DossierList(
            items=[], total=0, page=1, page_size=20
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dossiers.get_dossier_service"
                ) as mock_svc_factory,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                mock_svc = MagicMock()
                mock_svc.list_dossiers = AsyncMock(return_value=dossier_list)
                mock_svc_factory.return_value = mock_svc

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers?statut=en_cours&search=RC-2025",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        # Verify service was called with filters
        call_args = mock_svc.list_dossiers.call_args
        filters = call_args.kwargs.get("filters") or call_args[1].get("filters")
        assert filters.statut == DossierStatut.en_cours
        assert filters.search == "RC-2025"

    @pytest.mark.asyncio
    async def test_list_viewer_forbidden(self):
        """GET /dossiers as viewer returns 403."""
        _setup_overrides(role=AdminRole.viewer.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestDossierStats:
    @pytest.mark.asyncio
    async def test_stats_success(self):
        """GET /dossiers/stats returns KPIs."""
        _setup_overrides()
        stats = DossierStats(
            total=100, en_cours=30, valide=25, rejete=10,
            en_attente=20, complement=10, incomplet=5,
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.dossiers.get_dossier_service"
                ) as mock_svc_factory,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                mock_svc = MagicMock()
                mock_svc.get_dossier_stats = AsyncMock(return_value=stats)
                mock_svc_factory.return_value = mock_svc

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert data["en_cours"] == 30
        assert data["valide"] == 25


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImportDossiers:
    @pytest.mark.asyncio
    async def test_import_success_xlsx(self):
        """POST /dossiers/import with valid .xlsx returns 202."""
        _setup_overrides()
        mock_minio = MagicMock()
        mock_minio.put_object = AsyncMock()
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock()

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch("app.api.v1.dossiers.get_minio", return_value=mock_minio),
                patch("app.api.v1.dossiers.get_arq_pool", return_value=mock_arq),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/import",
                        files={"file": ("dossiers.xlsx", b"PK\x03\x04test", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 202
        data = response.json()
        assert "file_path" in data
        assert data["file_path"].startswith("imports/pending/")
        mock_minio.put_object.assert_called_once()
        mock_arq.enqueue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_bad_extension(self):
        """POST /dossiers/import with .exe returns 422."""
        _setup_overrides()

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/import",
                        files={"file": ("malicious.exe", b"MZ\x90", "application/octet-stream")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_import_file_too_large(self):
        """POST /dossiers/import with >10MB returns 422."""
        _setup_overrides()

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/import",
                        files={"file": ("big.xlsx", b"x" * (10 * 1024 * 1024 + 1), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_import_viewer_forbidden(self):
        """POST /dossiers/import as viewer returns 403."""
        _setup_overrides(role=AdminRole.viewer.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/import",
                        files={"file": ("test.xlsx", b"data", "application/octet-stream")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_import_supervisor_forbidden(self):
        """POST /dossiers/import as supervisor returns 403."""
        _setup_overrides(role=AdminRole.supervisor.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/import",
                        files={"file": ("test.xlsx", b"data", "application/octet-stream")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Sync logs
# ---------------------------------------------------------------------------


class TestSyncLogs:
    @pytest.mark.asyncio
    async def test_list_sync_logs(self):
        """GET /dossiers/sync-logs returns paginated list."""
        _setup_overrides()
        sl = _make_sync_log_orm()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [sl]
        data_result.scalars.return_value = mock_scalars

        mock_session = _mock_tenant_db_session(
            execute_side_effect=[count_result, data_result]
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers/sync-logs?page=1&page_size=10",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_get_sync_log_not_found(self):
        """GET /dossiers/sync-logs/{id} returns 404 when not found."""
        _setup_overrides()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/dossiers/sync-logs/{uuid.uuid4()}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_sync_log_success(self):
        """GET /dossiers/sync-logs/{id} returns sync log detail."""
        _setup_overrides()
        sl = _make_sync_log_orm()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=sl)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/dossiers/sync-logs/{sl.id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(sl.id)
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Sync configs
# ---------------------------------------------------------------------------


class TestSyncConfigs:
    @pytest.mark.asyncio
    async def test_list_sync_configs(self):
        """GET /dossiers/sync-configs returns all configs."""
        _setup_overrides()
        cfg = _make_sync_config_orm()
        mock_session = _mock_tenant_db_session(scalars_all=[cfg])

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        "/api/v1/dossiers/sync-configs",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_sync_config(self):
        """POST /dossiers/sync-configs creates a config."""
        _setup_overrides()
        cfg = _make_sync_config_orm()
        mock_session = _mock_tenant_db_session()

        async def fake_refresh(obj):
            obj.id = cfg.id
            obj.provider_type = cfg.provider_type
            obj.config_json = cfg.config_json
            obj.column_mapping = cfg.column_mapping
            obj.schedule_cron = cfg.schedule_cron
            obj.watched_folder = cfg.watched_folder
            obj.is_active = cfg.is_active
            obj.created_at = cfg.created_at
            obj.updated_at = cfg.updated_at

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/v1/dossiers/sync-configs",
                        json={
                            "column_mapping": {"N° Dossier": "numero", "Statut": "statut"},
                            "schedule_cron": "0 6 * * *",
                        },
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(cfg.id)
        assert data["is_active"] is True
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sync_config(self):
        """PUT /dossiers/sync-configs/{id} updates partial fields."""
        _setup_overrides()
        cfg = _make_sync_config_orm()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=cfg)
        mock_session.get = AsyncMock(return_value=cfg)

        async def fake_refresh(obj):
            obj.is_active = False
            obj.updated_at = datetime(2025, 7, 1, tzinfo=UTC)

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.put(
                        f"/api/v1/dossiers/sync-configs/{cfg.id}",
                        json={"is_active": False},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_sync_config_not_found(self):
        """PUT /dossiers/sync-configs/{id} returns 404 when not found."""
        _setup_overrides()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.put(
                        f"/api/v1/dossiers/sync-configs/{uuid.uuid4()}",
                        json={"is_active": False},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Dossier detail
# ---------------------------------------------------------------------------


class TestDossierDetail:
    @pytest.mark.asyncio
    async def test_get_dossier_success(self):
        """GET /dossiers/{id} returns dossier with history."""
        _setup_overrides()
        dossier = _make_dossier_orm(
            history=[
                MagicMock(
                    id=uuid.uuid4(),
                    field_changed="statut",
                    old_value="en_attente",
                    new_value="en_cours",
                    changed_at=datetime(2025, 4, 1, tzinfo=UTC),
                    sync_log_id=None,
                ),
            ],
        )
        mock_session = _mock_tenant_db_session(scalar_one_or_none=dossier)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/dossiers/{dossier.id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(dossier.id)
        assert data["numero"] == "RC-2025-001"
        assert len(data["history"]) == 1
        assert data["history"][0]["field_changed"] == "statut"

    @pytest.mark.asyncio
    async def test_get_dossier_not_found(self):
        """GET /dossiers/{id} returns 404 when not found."""
        _setup_overrides()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/dossiers/{uuid.uuid4()}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404
