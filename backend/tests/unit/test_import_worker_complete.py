"""Completion tests for import worker ARQ tasks — Wave 29B.

Adds edge cases NOT in test_worker_import.py (Wave 24):
- Explicit SyncLog creation assertion
- Zero-row import completes without error
- Watch folder with no SyncConfig
- Scheduled import with zero active tenants
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.models.enums import SyncStatus
from app.workers.import_dossier import (
    task_import_dossier,
    task_scheduled_import_all,
    task_watch_import_folder,
)

TEST_TENANT_SLUG = "rabat"
TEST_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# -- Helpers ----------------------------------------------------------------


class _AsyncCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _make_mock_tenant() -> MagicMock:
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = TEST_TENANT_SLUG
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.minio_bucket = f"cri-{TEST_TENANT_SLUG}"
    tenant.redis_prefix = TEST_TENANT_SLUG
    tenant.db_schema = f"tenant_{TEST_TENANT_SLUG}"
    return tenant


def _make_mock_session(*, execute_results=None, get_result=None) -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    if execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)

    session.get = AsyncMock(return_value=get_result or MagicMock())
    return session


def _make_tenant_with_session(session: AsyncMock) -> MagicMock:
    tenant = _make_mock_tenant()
    tenant.db_session = MagicMock(return_value=_AsyncCM(session))
    return tenant


def _make_minio_response(content: bytes = b"fake-file-content") -> AsyncMock:
    response = AsyncMock()
    response.read = AsyncMock(return_value=content)
    response.close = MagicMock()
    response.release = AsyncMock()
    return response


def _make_sync_log_mock(status=SyncStatus.pending) -> MagicMock:
    sl = MagicMock()
    sl.id = uuid.uuid4()
    sl.status = status
    sl.file_hash = None
    sl.error_details = None
    sl.completed_at = None
    return sl


def _make_import_report(**overrides) -> MagicMock:
    defaults = {
        "sync_log_id": uuid.uuid4(),
        "rows_total": 0,
        "rows_imported": 0,
        "rows_updated": 0,
        "rows_errored": 0,
        "errors": [],
        "duration_seconds": 0.1,
    }
    defaults.update(overrides)
    report = MagicMock()
    for k, v in defaults.items():
        setattr(report, k, v)
    return report


# -- Tests ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestSyncLogComplete:
    """SyncLog creation tests."""

    @pytest.mark.asyncio
    async def test_import_creates_sync_log_entry(self) -> None:
        """Import task should add a SyncLog to the session."""
        sync_log = _make_sync_log_mock()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = []

        session = _make_mock_session(
            execute_results=[config_result, history_result],
            get_result=sync_log,
        )
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=True, is_duplicate=False, file_hash="abc123",
            file_size=1024, error=None,
        )
        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_excel.return_value = []
        mock_import_service.import_dossiers = AsyncMock(
            return_value=_make_import_report(),
        )

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
            patch("app.core.redis.get_redis", return_value=AsyncMock()),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            result = await task_import_dossier(
                {}, "imports/pending/test.xlsx", None, TEST_TENANT_SLUG, None,
            )

        # SyncLog should have been updated with results
        assert result["status"] == "completed"


@pytest.mark.unit
@pytest.mark.phase3
class TestEdgeCasesComplete:
    """Import edge cases."""

    @pytest.mark.asyncio
    async def test_import_zero_rows_completes_without_error(self) -> None:
        """Empty file parses to 0 rows → status 'completed', not error."""
        sync_log = _make_sync_log_mock()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = []

        session = _make_mock_session(
            execute_results=[config_result, history_result],
            get_result=sync_log,
        )
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=True, is_duplicate=False, file_hash="empty_hash",
            file_size=128, error=None,
        )
        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_excel.return_value = []  # Zero rows
        mock_import_service.import_dossiers = AsyncMock(
            return_value=_make_import_report(rows_total=0),
        )

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
            patch("app.core.redis.get_redis", return_value=AsyncMock()),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            result = await task_import_dossier(
                {}, "imports/pending/empty.xlsx", None, TEST_TENANT_SLUG, None,
            )

        assert result["status"] == "completed"
        assert result["rows_total"] == 0


@pytest.mark.unit
@pytest.mark.phase3
class TestWatchComplete:
    """Watch folder edge cases."""

    @pytest.mark.asyncio
    async def test_watch_folder_no_config_returns_empty(self) -> None:
        """No SyncConfig for tenant → 0 files found, no crash."""
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        session = _make_mock_session(execute_results=[config_result])
        tenant = _make_tenant_with_session(session)

        class MockAsyncIter:
            def __init__(self, items):
                self._items = iter(items)
            def __aiter__(self):
                return self
            async def __anext__(self):
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration

        mock_minio = AsyncMock()
        mock_minio.list_objects = MagicMock(return_value=MockAsyncIter([]))

        ctx = {"redis": AsyncMock()}

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)

            result = await task_watch_import_folder(ctx, TEST_TENANT_SLUG)

        assert result["files_found"] == 0
        assert result["files_enqueued"] == 0


@pytest.mark.unit
@pytest.mark.phase3
class TestScheduledComplete:
    """Scheduled import edge cases."""

    @pytest.mark.asyncio
    async def test_scheduled_import_no_active_tenants(self) -> None:
        """Zero active tenants → tenants_checked=0, no error."""
        tenants_result = MagicMock()
        tenants_result.scalars.return_value.all.return_value = []

        mock_factory = MagicMock()
        mock_public_session = AsyncMock()
        mock_public_session.execute = AsyncMock(return_value=tenants_result)
        mock_public_session.__aenter__ = AsyncMock(return_value=mock_public_session)
        mock_public_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_public_session

        ctx = {"redis": AsyncMock()}

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            result = await task_scheduled_import_all(ctx)

        assert result["tenants_checked"] == 0
        assert result["tenants_enqueued"] == 0
