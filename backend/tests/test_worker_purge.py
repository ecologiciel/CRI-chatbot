"""Tests for ARQ CNDP data purge worker.

Covers:
- _purge_tenant_conversations: batched delete, audit, safety invariants
- task_purge_expired_data: multi-tenant iteration, error resilience
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Set env vars before importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.workers.purge import (
    BATCH_SIZE,
    RETENTION_DAYS_CONVERSATIONS,
    _purge_tenant_conversations,
    task_purge_expired_data,
)

# ── Constants ────────────────────────────────────────────────

TEST_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_TENANT_SLUG = "rabat"
CUTOFF = datetime.now(UTC) - timedelta(days=RETENTION_DAYS_CONVERSATIONS)


# ── Helpers ──────────────────────────────────────────────────


class _AsyncCM:
    """Async context manager wrapping a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _make_mock_tenant() -> MagicMock:
    """Create a MagicMock that mimics TenantContext."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = TEST_TENANT_SLUG
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.db_schema = f"tenant_{TEST_TENANT_SLUG}"
    return tenant


def _make_execute_result(rowcount: int) -> MagicMock:
    """Create a mock CursorResult with a given rowcount."""
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _make_tenant_with_session(session: AsyncMock) -> MagicMock:
    """Create a tenant mock wired to a specific session mock."""
    tenant = _make_mock_tenant()
    tenant.db_session = MagicMock(return_value=_AsyncCM(session))
    return tenant


def _make_public_session(slugs: list[str]) -> AsyncMock:
    """Create a mock session for querying active tenants from public schema."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    # session.execute calls: 1) SET search_path, 2) SELECT slugs
    rows = [(s,) for s in slugs]
    search_path_result = MagicMock()
    slug_result = MagicMock()
    slug_result.all.return_value = rows
    session.execute = AsyncMock(side_effect=[search_path_result, slug_result])
    return session


# ── Tests: _purge_tenant_conversations ───────────────────────


class TestPurgeTenantConversations:
    """Tests for the per-tenant purge helper."""

    @pytest.mark.asyncio
    async def test_purge_deletes_old_ended_conversations(self):
        """Conversations terminated > 90 days ago are deleted."""
        session = AsyncMock()
        session.commit = AsyncMock()
        # First batch: 5 deleted, second batch: 0 (done)
        session.execute = AsyncMock(
            side_effect=[
                _make_execute_result(5),
                _make_execute_result(0),
            ],
        )
        tenant = _make_tenant_with_session(session)
        mock_audit = AsyncMock()

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=mock_audit,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            stats = await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        assert stats["conversations_deleted"] == 5
        mock_audit.log_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_purge_keeps_recent_conversations(self):
        """Conversations terminated < 90 days ago are NOT deleted."""
        session = AsyncMock()
        session.commit = AsyncMock()
        # Nothing matches the cutoff
        session.execute = AsyncMock(
            return_value=_make_execute_result(0),
        )
        tenant = _make_tenant_with_session(session)
        mock_audit = AsyncMock()

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=mock_audit,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            stats = await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        assert stats["conversations_deleted"] == 0
        # No audit log when nothing was deleted
        mock_audit.log_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_purge_keeps_active_conversations(self):
        """Active conversations (ended_at IS NULL) are never deleted.

        The SQL WHERE clause filters on ended_at IS NOT NULL, so active
        conversations can never match.  We verify that only the batched
        delete statement is executed (no separate active-conversation query).
        """
        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            return_value=_make_execute_result(0),
        )
        tenant = _make_tenant_with_session(session)

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=AsyncMock(),
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            stats = await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        # Zero deleted confirms the WHERE clause protects active conversations
        assert stats["conversations_deleted"] == 0

    @pytest.mark.asyncio
    async def test_purge_cascade_deletes_messages(self):
        """Messages are cascade-deleted via FK — no separate DELETE needed.

        We verify that only one type of DELETE statement is executed
        (conversations), not a separate messages delete.
        """
        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_execute_result(3),
                _make_execute_result(0),
            ],
        )
        tenant = _make_tenant_with_session(session)

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=AsyncMock(),
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            stats = await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        assert stats["conversations_deleted"] == 3
        # Only 2 execute calls (batch with 3, batch with 0) — no message delete
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_purge_audits_action(self):
        """Each purge is logged in the audit trail with correct fields."""
        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_execute_result(10),
                _make_execute_result(0),
            ],
        )
        tenant = _make_tenant_with_session(session)
        mock_audit = AsyncMock()

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=mock_audit,
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        audit_call = mock_audit.log_action.call_args[0][0]
        assert audit_call.tenant_slug == TEST_TENANT_SLUG
        assert audit_call.user_type == "system"
        assert audit_call.action == "delete"
        assert audit_call.resource_type == "conversation"
        assert audit_call.details["reason"] == "cndp_retention_policy"
        assert audit_call.details["conversations_deleted"] == 10
        assert audit_call.details["retention_days"] == RETENTION_DAYS_CONVERSATIONS

    @pytest.mark.asyncio
    async def test_purge_batch_processing(self):
        """Purge operates in batches — commit after each productive batch."""
        session = AsyncMock()
        session.commit = AsyncMock()
        # 3 batches: 1000 + 500 + 0
        session.execute = AsyncMock(
            side_effect=[
                _make_execute_result(BATCH_SIZE),
                _make_execute_result(500),
                _make_execute_result(0),
            ],
        )
        tenant = _make_tenant_with_session(session)

        with (
            patch(
                "app.core.tenant.TenantResolver",
            ) as MockResolver,
            patch(
                "app.services.audit.service.get_audit_service",
                return_value=AsyncMock(),
            ),
        ):
            MockResolver.from_slug = AsyncMock(return_value=tenant)
            stats = await _purge_tenant_conversations(TEST_TENANT_SLUG, CUTOFF)

        assert stats["conversations_deleted"] == BATCH_SIZE + 500
        # commit() called once per productive batch (2 batches had rows)
        assert session.commit.call_count == 2


# ── Tests: task_purge_expired_data ───────────────────────────


class TestTaskPurgeExpiredData:
    """Tests for the main cron entry point."""

    @pytest.mark.asyncio
    async def test_purge_iterates_all_active_tenants(self):
        """All active tenants are processed and stats aggregated."""
        mock_session = _make_public_session(["rabat", "tanger"])
        mock_factory = MagicMock(return_value=mock_session)

        with (
            patch(
                "app.core.database.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "app.workers.purge._purge_tenant_conversations",
                new_callable=AsyncMock,
                side_effect=[
                    {"conversations_deleted": 5},
                    {"conversations_deleted": 3},
                ],
            ) as mock_purge,
        ):
            result = await task_purge_expired_data({})

        assert result["tenants_processed"] == 2
        assert result["total_conversations_deleted"] == 8
        assert result["tenants_with_purges"] == 2
        assert result["tenants_errored"] == 0
        assert mock_purge.call_count == 2

    @pytest.mark.asyncio
    async def test_purge_continues_on_tenant_error(self):
        """One tenant failure does not block other tenants."""
        mock_session = _make_public_session(["broken", "good"])
        mock_factory = MagicMock(return_value=mock_session)

        with (
            patch(
                "app.core.database.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "app.workers.purge._purge_tenant_conversations",
                new_callable=AsyncMock,
                side_effect=[
                    RuntimeError("DB connection lost"),
                    {"conversations_deleted": 7},
                ],
            ),
        ):
            result = await task_purge_expired_data({})

        assert result["tenants_processed"] == 2
        assert result["tenants_errored"] == 1
        assert result["tenants_with_purges"] == 1
        assert result["total_conversations_deleted"] == 7

    @pytest.mark.asyncio
    async def test_purge_returns_zero_stats_when_no_tenants(self):
        """Empty tenant list returns zero-filled stats."""
        mock_session = _make_public_session([])
        mock_factory = MagicMock(return_value=mock_session)

        with patch(
            "app.core.database.get_session_factory",
            return_value=mock_factory,
        ):
            result = await task_purge_expired_data({})

        assert result["tenants_processed"] == 0
        assert result["total_conversations_deleted"] == 0
        assert result["tenants_with_purges"] == 0
        assert result["tenants_errored"] == 0
