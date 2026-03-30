"""Rate limiting tests for all 3 implemented mechanisms.

Tests login lockout (AuthService), webhook rate limit (WhatsAppWebhookService),
and user message rate limit (MessageHandler).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import RateLimitExceededError
from app.services.whatsapp.webhook import WhatsAppWebhookService


class TestLoginRateLimiting:
    """Login rate limiting: 5 attempts / 15 min, 30 min lockout."""

    @pytest.mark.asyncio
    async def test_login_lockout_at_5_attempts(self):
        """After 5 failed attempts, lockout key is set with 1800s TTL."""
        mock_redis = AsyncMock()
        # Not locked out
        mock_redis.ttl = AsyncMock(return_value=-2)
        # 5th attempt
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch("app.services.auth.service.get_redis", return_value=mock_redis):
            from app.services.auth.service import AuthService

            service = AuthService()
            # _record_failed_attempt should set lockout on 5th attempt
            await service._record_failed_attempt("admin@test.ma")

        # Check lockout key was set
        mock_redis.setex.assert_called()
        lockout_call = mock_redis.setex.call_args
        assert "auth:lockout:admin@test.ma" in str(lockout_call)
        # TTL should be 1800 seconds (30 minutes)
        assert lockout_call[0][1] == 1800

    @pytest.mark.asyncio
    async def test_login_lockout_resets_on_success(self):
        """Successful login resets the attempt counter."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.services.auth.service.get_redis", return_value=mock_redis):
            from app.services.auth.service import AuthService

            service = AuthService()
            await service._reset_attempts("admin@test.ma")

        mock_redis.delete.assert_called_once_with("auth:login_attempts:admin@test.ma")

    @pytest.mark.asyncio
    async def test_login_attempt_window_15min(self):
        """First failed attempt sets expire with 900s (15 min) window."""
        mock_redis = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=-2)
        # First attempt
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch("app.services.auth.service.get_redis", return_value=mock_redis):
            from app.services.auth.service import AuthService

            service = AuthService()
            await service._record_failed_attempt("admin@test.ma")

        # expire should be called with 900 seconds
        mock_redis.expire.assert_called_once_with("auth:login_attempts:admin@test.ma", 900)


class TestWebhookRateLimiting:
    """Webhook rate limiting: 50 req/min per tenant."""

    @pytest.mark.asyncio
    async def test_webhook_allows_50_requests(self):
        """50th request passes without error."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=50)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            # Should not raise
            await WhatsAppWebhookService._check_rate_limit("alpha")

    @pytest.mark.asyncio
    async def test_webhook_rejects_51st(self):
        """51st request raises RateLimitExceededError."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=51)
        mock_redis.expire = AsyncMock()

        with (
            patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis),
            pytest.raises(RateLimitExceededError),
        ):
            await WhatsAppWebhookService._check_rate_limit("alpha")

    @pytest.mark.asyncio
    async def test_webhook_expire_set_on_first(self):
        """First request (incr=1) sets expire with 60s window."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            await WhatsAppWebhookService._check_rate_limit("alpha")

        mock_redis.expire.assert_called_once_with("alpha:rl:webhook", 60)


class TestUserMessageRateLimiting:
    """User WhatsApp rate limiting: 10 msg/min."""

    @pytest.mark.asyncio
    async def test_user_allows_10_messages(self, test_tenant):
        """10th message is not rate limited."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=10)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.handler.get_redis", return_value=mock_redis):
            from app.services.whatsapp.handler import MessageHandler

            result = await MessageHandler._check_user_rate_limit(test_tenant, "212600000001")

        assert result is False  # Not rate limited

    @pytest.mark.asyncio
    async def test_user_rejects_11th_message(self, test_tenant):
        """11th message is rate limited."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=11)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.handler.get_redis", return_value=mock_redis):
            from app.services.whatsapp.handler import MessageHandler

            result = await MessageHandler._check_user_rate_limit(test_tenant, "212600000001")

        assert result is True  # Rate limited
