"""Tests for archive_audit_logs ARQ worker (SECURITE.4).

Tests cover: import, JSON serialization (UUID/datetime), SHA-256
determinism, gzip round-trip, bucket creation, and full task execution.
"""

import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Import ---


class TestImport:
    def test_archive_worker_import(self):
        """archive_audit_logs task should be importable."""
        from app.workers.archive import archive_audit_logs

        assert archive_audit_logs is not None

    def test_worker_settings_import(self):
        """WorkerSettings should be importable."""
        from app.workers.archive import WorkerSettings

        assert WorkerSettings is not None
        assert WorkerSettings.cron_jobs  # Has at least one cron job


# --- JSON serialization ---


class TestJsonSerialization:
    def test_json_default_handles_uuid(self):
        """UUID objects should serialize to string."""
        from app.workers.archive import _json_default

        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert _json_default(uid) == "12345678-1234-5678-1234-567812345678"

    def test_json_default_handles_datetime(self):
        """datetime objects should serialize to ISO format."""
        from app.workers.archive import _json_default

        dt = datetime(2026, 3, 15, 14, 30, 0, tzinfo=UTC)
        assert _json_default(dt) == "2026-03-15T14:30:00+00:00"

    def test_json_default_raises_for_unknown(self):
        """Unknown types should raise TypeError."""
        from app.workers.archive import _json_default

        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_default(object())

    def test_json_handles_uuid_and_datetime_in_dumps(self):
        """Full json.dumps with custom default should work."""
        from app.workers.archive import _json_default

        data = [
            {
                "id": uuid.uuid4(),
                "action": "create",
                "created_at": datetime.now(UTC),
                "details": {"key": "value"},
            }
        ]
        result = json.dumps(data, default=_json_default, ensure_ascii=False)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert len(parsed) == 1


# --- SHA-256 determinism ---


class TestSha256:
    def test_sha256_deterministic(self):
        """Same input should always produce the same hash."""
        data = [{"id": "123", "action": "create", "tenant": "rabat"}]
        json_str = json.dumps(data, ensure_ascii=False)
        h1 = hashlib.sha256(json_str.encode()).hexdigest()
        h2 = hashlib.sha256(json_str.encode()).hexdigest()
        assert h1 == h2

    def test_sha256_changes_with_input(self):
        """Different input should produce different hash."""
        h1 = hashlib.sha256(b"data1").hexdigest()
        h2 = hashlib.sha256(b"data2").hexdigest()
        assert h1 != h2


# --- Gzip round-trip ---


class TestGzip:
    def test_gzip_roundtrip(self):
        """Compress then decompress should yield identical bytes."""
        data = [{"id": "123", "action": "create", "tenant": "rabat"}]
        json_bytes = json.dumps(data, ensure_ascii=False).encode()
        compressed = gzip.compress(json_bytes)
        decompressed = gzip.decompress(compressed)
        assert decompressed == json_bytes

    def test_gzip_is_smaller(self):
        """Compressed output should be smaller for typical JSON payloads."""
        data = [{"id": str(uuid.uuid4()), "action": "create"} for _ in range(100)]
        json_bytes = json.dumps(data).encode()
        compressed = gzip.compress(json_bytes)
        assert len(compressed) < len(json_bytes)


# --- Week boundary calculation ---


class TestWeekBoundaries:
    def test_previous_week_boundaries(self):
        """Boundaries should span Monday 00:00 to Sunday 23:59:59."""
        from app.workers.archive import _previous_week_boundaries

        start, end = _previous_week_boundaries()

        # Start should be a Monday
        assert start.weekday() == 0  # Monday
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0

        # End should be the following Sunday
        assert end.weekday() == 6  # Sunday
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59

        # Should span exactly 6 days + 23:59:59
        diff = end - start
        assert diff.days == 6


# --- Bucket creation ---


class TestEnsureBucket:
    @pytest.mark.asyncio
    async def test_ensure_bucket_creates_when_missing(self):
        """Should create bucket if it does not exist."""
        from app.workers.archive import _ensure_bucket

        minio = AsyncMock()
        minio.bucket_exists = AsyncMock(return_value=False)
        minio.make_bucket = AsyncMock()

        await _ensure_bucket(minio, "cri-system-archive")

        minio.bucket_exists.assert_called_once_with("cri-system-archive")
        minio.make_bucket.assert_called_once_with("cri-system-archive")

    @pytest.mark.asyncio
    async def test_ensure_bucket_skips_when_exists(self):
        """Should not create bucket if it already exists."""
        from app.workers.archive import _ensure_bucket

        minio = AsyncMock()
        minio.bucket_exists = AsyncMock(return_value=True)

        await _ensure_bucket(minio, "cri-system-archive")

        minio.make_bucket.assert_not_called()


# --- Full task execution ---


def _make_audit_log_row(**overrides):
    """Create a mock AuditLog ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_slug": "rabat",
        "user_id": uuid.uuid4(),
        "user_type": "admin",
        "action": "create",
        "resource_type": "kb_document",
        "resource_id": str(uuid.uuid4()),
        "ip_address": "10.0.0.1",
        "user_agent": "Mozilla/5.0",
        "details": {"key": "value"},
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


class TestArchiveAuditLogs:
    """Integration tests using real AuditLog model (SQLAlchemy needs it)."""

    @pytest.mark.asyncio
    async def test_archive_success(self):
        """Full task: query -> serialize -> hash -> compress -> upload."""
        from app.workers.archive import archive_audit_logs

        rows = [_make_audit_log_row() for _ in range(5)]

        # Mock DB session — use real AuditLog model for select() compatibility
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(return_value=mock_session)

        # Mock MinIO
        mock_minio = AsyncMock()
        mock_minio.bucket_exists = AsyncMock(return_value=True)
        mock_minio.put_object = AsyncMock()

        with (
            patch("app.core.database.get_session_factory", return_value=mock_factory),
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            result = await archive_audit_logs({})

        assert result["status"] == "ok"
        assert result["row_count"] == 5
        assert result["sha256"]
        assert result["object_name"].startswith("audit_logs_")
        assert result["object_name"].endswith(".json.gz")
        assert result["compressed_bytes"] > 0
        assert result["uncompressed_bytes"] > 0

        # MinIO should have received one upload
        mock_minio.put_object.assert_called_once()
        call_args = mock_minio.put_object.call_args
        assert call_args[0][0] == "cri-system-archive"  # bucket
        assert call_args[1]["content_type"] == "application/gzip"
        assert "x-amz-meta-sha256" in call_args[1]["metadata"]

    @pytest.mark.asyncio
    async def test_archive_empty_week(self):
        """No audit logs in the period -- still uploads an empty JSON array."""
        from app.workers.archive import archive_audit_logs

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock(return_value=mock_session)

        mock_minio = AsyncMock()
        mock_minio.bucket_exists = AsyncMock(return_value=True)
        mock_minio.put_object = AsyncMock()

        with (
            patch("app.core.database.get_session_factory", return_value=mock_factory),
            patch("app.core.minio.get_minio", return_value=mock_minio),
        ):
            result = await archive_audit_logs({})

        assert result["status"] == "ok"
        assert result["row_count"] == 0
        mock_minio.put_object.assert_called_once()
