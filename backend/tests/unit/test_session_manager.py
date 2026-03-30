"""Unit tests for WhatsAppSessionManager — sessions, quota, dedup."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.whatsapp.session import WhatsAppSessionManager

_REDIS_PATCH = "app.services.whatsapp.session.get_redis"


def _make_redis(session_data=None, quota_results=None, dedup_result=True):
    """Create a mock Redis for session tests."""
    redis = AsyncMock()
    if session_data is not None:
        redis.get = AsyncMock(return_value=json.dumps(session_data))
    else:
        redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()

    pipe = AsyncMock()
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.get = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(
        return_value=quota_results or [0, 0],
    )
    redis.pipeline = MagicMock(return_value=pipe)
    redis._pipe = pipe

    # For is_duplicate_message: SET NX returns True if new, None/False if exists
    redis.set = AsyncMock(return_value=dedup_result)
    return redis


class TestNewSession:
    """Creating a new session."""

    @pytest.mark.asyncio
    async def test_create_new_session(self, tenant_context):
        """No existing session: is_active=True, message_count=1."""
        redis = _make_redis()
        # get returns None for new session, set returns True
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            session = await manager.get_or_create_session(
                tenant_context,
                "+212600000001",
            )

        assert session.is_active is True
        assert session.is_template_required is False
        assert session.message_count == 1
        assert session.started_at is not None


class TestExistingSession:
    """Updating an existing session."""

    @pytest.mark.asyncio
    async def test_existing_session_increments(self, tenant_context):
        """Existing session: message_count incremented, TTL refreshed."""
        existing = {
            "started_at": "2026-03-27T10:00:00+00:00",
            "last_message_at": "2026-03-27T10:05:00+00:00",
            "message_count": 3,
        }
        redis = _make_redis(session_data=existing)
        redis.get = AsyncMock(return_value=json.dumps(existing))
        redis.set = AsyncMock(return_value=True)

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            session = await manager.get_or_create_session(
                tenant_context,
                "+212600000001",
            )

        assert session.message_count == 4
        assert session.is_active is True


class TestExpiredSession:
    """Expired session requires template."""

    @pytest.mark.asyncio
    async def test_expired_requires_template(self, tenant_context):
        """get_session with no data: is_template_required=True."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            session = await manager.get_session(
                tenant_context,
                "+212600000001",
            )

        assert session.is_active is False
        assert session.is_template_required is True
        assert session.message_count == 0


class TestQuota:
    """Quota tracking and exhaustion."""

    @pytest.mark.asyncio
    async def test_quota_exhausted_at_limit(self, tenant_context):
        """annual_count == annual_limit: remaining=0, is_exhausted=True."""
        redis = _make_redis(quota_results=[5000, 100_000])

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            quota = await manager.check_quota(tenant_context)

        assert quota.monthly_count == 5000
        assert quota.annual_count == 100_000
        assert quota.remaining == 0
        assert quota.is_exhausted is True
        assert quota.is_warning is True


class TestDedup:
    """Message deduplication via SET NX."""

    @pytest.mark.asyncio
    async def test_new_message_not_duplicate(self, tenant_context):
        """SET NX returns True (new key set) → not duplicate."""
        redis = _make_redis(dedup_result=True)

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            is_dup = await manager.is_duplicate_message(
                tenant_context,
                "wamid.new123",
            )

        assert is_dup is False

    @pytest.mark.asyncio
    async def test_existing_message_is_duplicate(self, tenant_context):
        """SET NX returns None (key exists) → duplicate."""
        redis = _make_redis(dedup_result=None)

        with patch(_REDIS_PATCH, return_value=redis):
            manager = WhatsAppSessionManager()
            is_dup = await manager.is_duplicate_message(
                tenant_context,
                "wamid.existing456",
            )

        assert is_dup is True
