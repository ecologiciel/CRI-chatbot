"""Tests for WhatsAppSessionManager.

Covers session lifecycle, quota tracking, and message deduplication.
All Redis interactions are mocked.
"""

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure env vars are set before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-jwt-testing-only")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test_app_secret")

from app.core.tenant import TenantContext
from app.services.whatsapp.session import (
    DEFAULT_ANNUAL_LIMIT,
    DEDUP_TTL,
    SESSION_TTL,
    QuotaInfo,
    SessionInfo,
    WhatsAppSessionManager,
)

TEST_TENANT_ID = uuid.uuid4()
TEST_PHONE = "+212600000001"


def _make_tenant_context(**overrides) -> TenantContext:
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat-Salé-Kénitra",
        "status": "active",
        "whatsapp_config": {
            "phone_number_id": "111222333",
            "access_token": "test_token",
            "annual_message_limit": 100_000,
        },
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


def _make_session_json(message_count: int = 1) -> str:
    """Create a session JSON string as stored in Redis."""
    return json.dumps({
        "started_at": "2026-03-26T10:00:00+00:00",
        "last_message_at": "2026-03-26T10:00:00+00:00",
        "message_count": message_count,
    })


class TestSessionManagement:
    """Tests for session creation, retrieval, and lifecycle."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """New phone creates a fresh session with is_active=True."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # No existing session
        mock_redis.set = AsyncMock(return_value=True)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.get_or_create_session(tenant, TEST_PHONE)

        assert result.is_active is True
        assert result.is_template_required is False
        assert result.message_count == 1
        assert result.started_at is not None
        assert result.last_message_at is not None

        # Verify Redis SET was called with correct key and TTL
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == f"rabat:wa_session:{TEST_PHONE}"
        assert call_args[1]["ex"] == SESSION_TTL

    @pytest.mark.asyncio
    async def test_update_existing_session(self):
        """Existing session gets updated: message_count incremented, TTL refreshed."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_make_session_json(message_count=3))
        mock_redis.set = AsyncMock(return_value=True)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.get_or_create_session(tenant, TEST_PHONE)

        assert result.is_active is True
        assert result.is_template_required is False
        assert result.message_count == 4  # 3 + 1

        # Verify TTL was refreshed
        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == SESSION_TTL

    @pytest.mark.asyncio
    async def test_session_ttl_set_correctly(self):
        """Verify 24h TTL (86400s) is set on session creation."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            await manager.get_or_create_session(tenant, TEST_PHONE)

        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == 86400  # SESSION_TTL

    @pytest.mark.asyncio
    async def test_template_required_outside_window(self):
        """Expired session returns is_template_required=True."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Session expired

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.get_session(tenant, TEST_PHONE)

        assert result.is_active is False
        assert result.is_template_required is True
        assert result.started_at is None
        assert result.message_count == 0

    @pytest.mark.asyncio
    async def test_get_active_session(self):
        """get_session returns active info for existing session."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_make_session_json(message_count=5))

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.get_session(tenant, TEST_PHONE)

        assert result.is_active is True
        assert result.is_template_required is False
        assert result.message_count == 5

    @pytest.mark.asyncio
    async def test_close_session(self):
        """close_session deletes the Redis key."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            await manager.close_session(tenant, TEST_PHONE)

        mock_redis.delete.assert_called_once_with(
            f"rabat:wa_session:{TEST_PHONE}"
        )


class TestQuotaTracking:
    """Tests for outbound message quota tracking."""

    @pytest.mark.asyncio
    async def test_quota_tracking(self):
        """Incrementing quota updates monthly and annual counters."""
        mock_pipe = AsyncMock()
        mock_pipe.incr = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=[1, True, 1, True])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            await manager.increment_quota(tenant)

        # Verify pipeline called INCR on both keys
        assert mock_pipe.incr.call_count == 2
        incr_calls = [str(c) for c in mock_pipe.incr.call_args_list]
        assert any("wa:quota:" in c for c in incr_calls)
        assert any("wa:quota:annual:" in c for c in incr_calls)

    @pytest.mark.asyncio
    async def test_check_quota_normal(self):
        """Quota check returns correct counts and remaining."""
        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=["500", "3000"])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.check_quota(tenant)

        assert result.monthly_count == 500
        assert result.annual_count == 3000
        assert result.annual_limit == 100_000
        assert result.remaining == 97_000
        assert result.is_warning is False
        assert result.is_exhausted is False

    @pytest.mark.asyncio
    async def test_quota_exhausted(self):
        """Quota at or above limit returns is_exhausted=True."""
        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=["8000", "100000"])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.check_quota(tenant)

        assert result.annual_count == 100_000
        assert result.remaining == 0
        assert result.is_exhausted is True
        assert result.is_warning is True

    @pytest.mark.asyncio
    async def test_quota_warning(self):
        """Quota at 80% triggers warning flag."""
        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=["5000", "80000"])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.check_quota(tenant)

        assert result.is_warning is True
        assert result.is_exhausted is False
        assert result.remaining == 20_000

    @pytest.mark.asyncio
    async def test_quota_default_limit_no_config(self):
        """Tenant without whatsapp_config uses DEFAULT_ANNUAL_LIMIT."""
        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=["100", "1000"])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tenant = _make_tenant_context(whatsapp_config=None)
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.check_quota(tenant)

        assert result.annual_limit == DEFAULT_ANNUAL_LIMIT


class TestDeduplication:
    """Tests for message deduplication via SET NX."""

    @pytest.mark.asyncio
    async def test_dedup_new_message(self):
        """First occurrence of wamid returns False (not duplicate)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # Key was set (new)

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.is_duplicate_message(tenant, "wamid.test123")

        assert result is False  # Not duplicate

        # Verify SET NX with correct TTL
        mock_redis.set.assert_called_once_with(
            "rabat:dedup:wamid.test123", "1", ex=DEDUP_TTL, nx=True,
        )

    @pytest.mark.asyncio
    async def test_dedup_duplicate_message(self):
        """Second occurrence of same wamid returns True (duplicate)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # Key already exists

        tenant = _make_tenant_context()
        manager = WhatsAppSessionManager()

        with patch("app.services.whatsapp.session.get_redis", return_value=mock_redis):
            result = await manager.is_duplicate_message(tenant, "wamid.test123")

        assert result is True  # Duplicate
