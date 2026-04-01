"""Tests for ARQ dossier import worker tasks.

Covers:
- task_import_dossier: download, validate, parse, import, notifications
- task_watch_import_folder: list, hash-check, enqueue, move
- task_scheduled_import_all: iterate tenants, enqueue watch tasks
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set env vars before importing app modules
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

# ── Constants ────────────────────────────────────────────────

TEST_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_TENANT_SLUG = "rabat"
TEST_SYNC_LOG_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TEST_CONFIG_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


# ── Helpers ──────────────────────────────────────────────────


class _AsyncCM:
    """Async context manager wrapping a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


class MockAsyncIter:
    """Async iterable for mocking miniopy_async list_objects."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_tenant() -> MagicMock:
    """Create a MagicMock that mimics TenantContext."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = TEST_TENANT_SLUG
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.minio_bucket = f"cri-{TEST_TENANT_SLUG}"
    tenant.redis_prefix = TEST_TENANT_SLUG
    tenant.db_schema = f"tenant_{TEST_TENANT_SLUG}"
    return tenant


def _make_mock_session(
    *,
    execute_results: list | None = None,
    get_result: MagicMock | None = None,
) -> AsyncMock:
    """Create a mock async DB session.

    Args:
        execute_results: List of mock results for successive session.execute() calls.
        get_result: Return value for session.get() calls.
    """
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

    if get_result is not None:
        session.get = AsyncMock(return_value=get_result)
    else:
        session.get = AsyncMock(return_value=MagicMock())

    return session


def _make_tenant_with_session(session: AsyncMock) -> MagicMock:
    """Create a tenant mock wired to a specific session mock."""
    tenant = _make_mock_tenant()
    tenant.db_session = MagicMock(return_value=_AsyncCM(session))
    return tenant


def _make_minio_response(content: bytes = b"fake-file-content") -> AsyncMock:
    """Create a mock MinIO get_object response."""
    response = AsyncMock()
    response.read = AsyncMock(return_value=content)
    response.close = MagicMock()
    response.release = AsyncMock()
    return response


def _make_sync_log_mock(
    sync_log_id: uuid.UUID = TEST_SYNC_LOG_ID,
    status: SyncStatus = SyncStatus.pending,
) -> MagicMock:
    """Create a mock SyncLog ORM instance."""
    sl = MagicMock()
    sl.id = sync_log_id
    sl.status = status
    sl.file_hash = None
    sl.error_details = None
    sl.completed_at = None
    return sl


def _make_import_report(
    sync_log_id: uuid.UUID = TEST_SYNC_LOG_ID,
    rows_total: int = 10,
    rows_imported: int = 8,
    rows_updated: int = 2,
    rows_errored: int = 0,
) -> MagicMock:
    """Create a mock ImportReport."""
    report = MagicMock()
    report.sync_log_id = sync_log_id
    report.rows_total = rows_total
    report.rows_imported = rows_imported
    report.rows_updated = rows_updated
    report.rows_errored = rows_errored
    report.errors = []
    report.duration_seconds = 1.5
    return report


# ── Tests: task_import_dossier ───────────────────────────────


class TestTaskImportDossier:
    """Tests for the task_import_dossier ARQ task."""

    @pytest.mark.asyncio
    async def test_import_skips_duplicate_hash(self):
        """If the file hash already exists in sync_logs → skip."""
        session = _make_mock_session(get_result=_make_sync_log_mock())
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=False,
            is_duplicate=True,
            file_hash="abc123def456",
            file_size=1024,
            error=None,
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            result = await task_import_dossier(
                {}, "imports/pending/test.xlsx", None, TEST_TENANT_SLUG, None,
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate_hash"
        # import_dossiers should NOT be called
        mock_import_service.import_dossiers.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_invalid_file_fails(self):
        """If validate_file returns is_valid=False → sync_log failed."""
        sync_log = _make_sync_log_mock()
        session = _make_mock_session(get_result=sync_log)
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=False,
            is_duplicate=False,
            file_hash=None,
            file_size=0,
            error="Extension non autorisée : .txt",
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            result = await task_import_dossier(
                {}, "imports/pending/test.txt", None, TEST_TENANT_SLUG, None,
            )

        assert result["status"] == "failed"
        assert "Extension" in result["reason"]
        assert sync_log.status == SyncStatus.failed

    @pytest.mark.asyncio
    async def test_import_success_publishes_notifications(self):
        """Status changes are published to Redis notification queue."""
        sync_log = _make_sync_log_mock()

        # Mock DossierHistory entries with statut changes
        history_entry = MagicMock()
        history_entry.dossier_id = uuid.uuid4()
        history_entry.old_value = "en_attente"
        history_entry.new_value = "valide"
        history_entry.changed_at = datetime.now(UTC)

        # Session execute calls:
        # 1. SyncConfig query
        # 2. DossierHistory query
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = [history_entry]

        session = _make_mock_session(
            execute_results=[config_result, history_result],
            get_result=sync_log,
        )
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=True,
            is_duplicate=False,
            file_hash="abc123",
            file_size=1024,
            error=None,
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_excel.return_value = [MagicMock(row_number=1)]
        mock_import_service.sanitize_row.side_effect = lambda r: r
        mock_import_service.import_dossiers = AsyncMock(
            return_value=_make_import_report(),
        )

        mock_redis = AsyncMock()

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
            patch("app.core.redis.get_redis", return_value=mock_redis),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            result = await task_import_dossier(
                {}, "imports/pending/dossiers.xlsx", None, TEST_TENANT_SLUG, None,
            )

        assert result["status"] == "completed"
        assert result["notifications_published"] == 1
        mock_redis.rpush.assert_called_once()
        call_args = mock_redis.rpush.call_args
        assert call_args[0][0] == f"{TEST_TENANT_SLUG}:notification:dossier_changes"
        payload = json.loads(call_args[0][1])
        assert payload["old_statut"] == "en_attente"
        assert payload["new_statut"] == "valide"

    @pytest.mark.asyncio
    async def test_csv_file_uses_parse_csv(self):
        """File ending in .csv triggers parse_csv, not parse_excel."""
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
            is_valid=True, is_duplicate=False, file_hash="xyz", file_size=512, error=None,
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_csv.return_value = []
        mock_import_service.import_dossiers = AsyncMock(
            return_value=_make_import_report(rows_total=0, rows_imported=0, rows_updated=0),
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

            await task_import_dossier(
                {}, "imports/pending/data.csv", None, TEST_TENANT_SLUG, None,
            )

        mock_import_service.parse_csv.assert_called_once()
        mock_import_service.parse_excel.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_sets_sync_log_failed_and_reraises(self):
        """An exception during parsing sets SyncLog to failed and re-raises."""
        sync_log = _make_sync_log_mock()
        session = _make_mock_session(get_result=sync_log)
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=True, is_duplicate=False, file_hash="abc", file_size=1024, error=None,
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_excel.side_effect = ValueError("Corrupted file")

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(return_value=config_result)

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            with pytest.raises(ValueError, match="Corrupted file"):
                await task_import_dossier(
                    {}, "imports/pending/broken.xlsx", None, TEST_TENANT_SLUG, None,
                )

        # SyncLog should be marked failed
        assert sync_log.status == SyncStatus.failed

    @pytest.mark.asyncio
    async def test_tempfile_cleaned_on_error(self):
        """Temp file is deleted even when an exception occurs."""
        session = _make_mock_session(get_result=_make_sync_log_mock())
        tenant = _make_tenant_with_session(session)

        validation = MagicMock(
            is_valid=True, is_duplicate=False, file_hash="abc", file_size=1024, error=None,
        )

        mock_import_service = MagicMock()
        mock_import_service.validate_file = AsyncMock(return_value=validation)
        mock_import_service.parse_excel.side_effect = RuntimeError("boom")

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=config_result)

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio") as mock_get_minio,
            patch(
                "app.services.dossier.import_service.get_dossier_import_service",
                return_value=mock_import_service,
            ),
            patch("os.path.exists", return_value=True),
            patch("os.unlink") as mock_unlink,
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            mock_get_minio.return_value.get_object = AsyncMock(
                return_value=_make_minio_response(),
            )

            with pytest.raises(RuntimeError, match="boom"):
                await task_import_dossier(
                    {}, "imports/pending/test.xlsx", None, TEST_TENANT_SLUG, None,
                )

        mock_unlink.assert_called_once()


# ── Tests: task_watch_import_folder ──────────────────────────


class TestTaskWatchImportFolder:
    """Tests for the task_watch_import_folder ARQ task."""

    @pytest.mark.asyncio
    async def test_watch_lists_and_queues_new_files(self):
        """New files are discovered, hashed, and enqueued for import."""
        config = MagicMock()
        config.id = TEST_CONFIG_ID
        config.watched_folder = "imports/pending/"
        config.is_active = True

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = config

        # Hash check: no existing sync_log for these hashes
        hash_result = MagicMock()
        hash_result.scalar_one_or_none.return_value = None

        session = _make_mock_session(execute_results=[config_result, hash_result, hash_result])
        tenant = _make_tenant_with_session(session)

        # Two files in pending folder
        obj1 = MagicMock(object_name="imports/pending/file1.xlsx")
        obj2 = MagicMock(object_name="imports/pending/file2.csv")

        mock_minio = AsyncMock()
        mock_minio.list_objects = MagicMock(return_value=MockAsyncIter([obj1, obj2]))
        mock_minio.get_object = AsyncMock(return_value=_make_minio_response(b"data"))
        mock_minio.copy_object = AsyncMock()
        mock_minio.remove_object = AsyncMock()

        mock_arq_redis = AsyncMock()
        ctx = {"redis": mock_arq_redis}

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)

            result = await task_watch_import_folder(ctx, TEST_TENANT_SLUG)

        assert result["files_found"] == 2
        assert result["files_enqueued"] == 2
        assert result["files_skipped"] == 0
        assert mock_arq_redis.enqueue_job.call_count == 2

    @pytest.mark.asyncio
    async def test_watch_skips_already_imported_hash(self):
        """Files whose hash already exists in sync_logs are skipped."""
        config = MagicMock()
        config.id = TEST_CONFIG_ID
        config.watched_folder = "imports/pending/"

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = config

        # Hash check: existing sync_log found (not None)
        hash_result = MagicMock()
        hash_result.scalar_one_or_none.return_value = uuid.uuid4()

        session = _make_mock_session(execute_results=[config_result, hash_result])
        tenant = _make_tenant_with_session(session)

        obj1 = MagicMock(object_name="imports/pending/old_file.xlsx")

        mock_minio = AsyncMock()
        mock_minio.list_objects = MagicMock(return_value=MockAsyncIter([obj1]))
        mock_minio.get_object = AsyncMock(return_value=_make_minio_response(b"old"))
        mock_minio.copy_object = AsyncMock()
        mock_minio.remove_object = AsyncMock()

        mock_arq_redis = AsyncMock()
        ctx = {"redis": mock_arq_redis}

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)

            result = await task_watch_import_folder(ctx, TEST_TENANT_SLUG)

        assert result["files_found"] == 1
        assert result["files_skipped"] == 1
        assert result["files_enqueued"] == 0
        mock_arq_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_moves_files_to_processed(self):
        """Enqueued files are moved to imports/processed/{date}/."""
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = MagicMock(
            id=TEST_CONFIG_ID, watched_folder=None, is_active=True,
        )

        hash_result = MagicMock()
        hash_result.scalar_one_or_none.return_value = None

        session = _make_mock_session(execute_results=[config_result, hash_result])
        tenant = _make_tenant_with_session(session)

        obj1 = MagicMock(object_name="imports/pending/dossiers.xlsx")

        mock_minio = AsyncMock()
        mock_minio.list_objects = MagicMock(return_value=MockAsyncIter([obj1]))
        mock_minio.get_object = AsyncMock(return_value=_make_minio_response(b"data"))
        mock_minio.copy_object = AsyncMock()
        mock_minio.remove_object = AsyncMock()

        ctx = {"redis": AsyncMock()}

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)

            await task_watch_import_folder(ctx, TEST_TENANT_SLUG)

        # Verify copy + delete for move
        mock_minio.copy_object.assert_called_once()
        mock_minio.remove_object.assert_called_once()

        # Check destination path includes date and filename
        copy_args = mock_minio.copy_object.call_args
        dest_path = copy_args[0][1]  # second positional arg
        assert "imports/processed/" in dest_path
        assert "dossiers.xlsx" in dest_path

    @pytest.mark.asyncio
    async def test_watch_ignores_non_import_extensions(self):
        """Files with non-import extensions (.txt, .pdf) are ignored."""
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        session = _make_mock_session(execute_results=[config_result])
        tenant = _make_tenant_with_session(session)

        obj_txt = MagicMock(object_name="imports/pending/readme.txt")
        obj_pdf = MagicMock(object_name="imports/pending/report.pdf")

        mock_minio = AsyncMock()
        mock_minio.list_objects = MagicMock(return_value=MockAsyncIter([obj_txt, obj_pdf]))

        ctx = {"redis": AsyncMock()}

        with (
            patch("app.core.tenant.TenantResolver") as MockResolver,
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)

            result = await task_watch_import_folder(ctx, TEST_TENANT_SLUG)

        assert result["files_found"] == 0
        assert result["files_enqueued"] == 0
        mock_minio.get_object.assert_not_called()


# ── Tests: task_scheduled_import_all ─────────────────────────


class TestTaskScheduledImportAll:
    """Tests for the task_scheduled_import_all cron task."""

    @pytest.mark.asyncio
    async def test_enqueues_tenants_with_cron_config(self):
        """Tenants with active SyncConfig + schedule_cron get enqueued."""
        # Two active tenants
        tenant_rabat = MagicMock(slug="rabat", status="active")
        tenant_tanger = MagicMock(slug="tanger", status="active")

        # Public schema query returns both tenants
        tenants_result = MagicMock()
        tenants_result.scalars.return_value.all.return_value = [tenant_rabat, tenant_tanger]

        mock_factory = MagicMock()
        mock_public_session = AsyncMock()
        mock_public_session.execute = AsyncMock(return_value=tenants_result)
        mock_public_session.__aenter__ = AsyncMock(return_value=mock_public_session)
        mock_public_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_public_session

        # Rabat has cron config, Tanger does not
        config_with_cron = MagicMock(schedule_cron="0 6 * * *", is_active=True)
        rabat_config_result = MagicMock()
        rabat_config_result.scalar_one_or_none.return_value = config_with_cron

        tanger_config_result = MagicMock()
        tanger_config_result.scalar_one_or_none.return_value = None

        rabat_session = _make_mock_session(execute_results=[rabat_config_result])
        tanger_session = _make_mock_session(execute_results=[tanger_config_result])

        rabat_tenant_ctx = _make_tenant_with_session(rabat_session)
        tanger_tenant_ctx = _make_tenant_with_session(tanger_session)

        mock_arq_redis = AsyncMock()
        ctx = {"redis": mock_arq_redis}

        async def mock_from_slug(slug):
            return rabat_tenant_ctx if slug == "rabat" else tanger_tenant_ctx

        with (
            patch("app.core.database.get_session_factory", return_value=mock_factory),
            patch("app.core.tenant.TenantResolver") as MockResolver,
        ):
            MockResolver.from_slug = AsyncMock(side_effect=mock_from_slug)

            result = await task_scheduled_import_all(ctx)

        assert result["tenants_checked"] == 2
        assert result["tenants_enqueued"] == 1
        mock_arq_redis.enqueue_job.assert_called_once_with(
            "task_watch_import_folder", "rabat",
        )

    @pytest.mark.asyncio
    async def test_continues_on_tenant_error(self):
        """If one tenant errors, others still get processed."""
        tenant_bad = MagicMock(slug="broken", status="active")
        tenant_good = MagicMock(slug="good", status="active")

        tenants_result = MagicMock()
        tenants_result.scalars.return_value.all.return_value = [tenant_bad, tenant_good]

        mock_factory = MagicMock()
        mock_public_session = AsyncMock()
        mock_public_session.execute = AsyncMock(return_value=tenants_result)
        mock_public_session.__aenter__ = AsyncMock(return_value=mock_public_session)
        mock_public_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_public_session

        good_config_result = MagicMock()
        good_config_result.scalar_one_or_none.return_value = MagicMock(
            schedule_cron="0 6 * * *",
        )
        good_session = _make_mock_session(execute_results=[good_config_result])
        good_tenant_ctx = _make_tenant_with_session(good_session)

        mock_arq_redis = AsyncMock()
        ctx = {"redis": mock_arq_redis}

        async def mock_from_slug(slug):
            if slug == "broken":
                raise RuntimeError("Tenant resolution failed")
            return good_tenant_ctx

        with (
            patch("app.core.database.get_session_factory", return_value=mock_factory),
            patch("app.core.tenant.TenantResolver") as MockResolver,
        ):
            MockResolver.from_slug = AsyncMock(side_effect=mock_from_slug)

            result = await task_scheduled_import_all(ctx)

        # Should not raise, and good tenant should be enqueued
        assert result["tenants_checked"] == 2
        assert result["tenants_enqueued"] == 1
        mock_arq_redis.enqueue_job.assert_called_once_with(
            "task_watch_import_folder", "good",
        )
