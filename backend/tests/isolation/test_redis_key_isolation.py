"""Redis key prefix isolation tests.

Verifies that all Redis operations are scoped to the tenant's prefix,
making cross-tenant key access impossible at the application level.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.whatsapp.webhook import WhatsAppWebhookService


class TestRedisKeyIsolation:
    """Redis keys must always be prefixed with the tenant slug."""

    def test_redis_prefix_per_tenant(self, tenant_alpha, tenant_beta):
        """Each tenant has a distinct redis_prefix."""
        assert tenant_alpha.redis_prefix == "alpha"
        assert tenant_beta.redis_prefix == "beta"
        assert tenant_alpha.redis_prefix != tenant_beta.redis_prefix

    @pytest.mark.asyncio
    async def test_webhook_rate_limit_key_scoped(self):
        """Webhook rate limit uses key {slug}:rl:webhook."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            await WhatsAppWebhookService._check_rate_limit("alpha")

        mock_redis.incr.assert_called_once_with("alpha:rl:webhook")

    @pytest.mark.asyncio
    async def test_dedup_key_scoped(self):
        """Dedup uses key {slug}:dedup:{wamid}."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            result = await WhatsAppWebhookService._mark_if_new("alpha", "wamid.123")

        assert result is True
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "alpha:dedup:wamid.123"

    @pytest.mark.asyncio
    async def test_two_tenants_same_wamid_different_keys(self):
        """Same wamid for two tenants produces different Redis keys."""
        captured_keys = []
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            await WhatsAppWebhookService._mark_if_new("alpha", "wamid.shared")
            captured_keys.append(mock_redis.set.call_args[0][0])

            mock_redis.set.reset_mock()

            await WhatsAppWebhookService._mark_if_new("beta", "wamid.shared")
            captured_keys.append(mock_redis.set.call_args[0][0])

        assert captured_keys[0] == "alpha:dedup:wamid.shared"
        assert captured_keys[1] == "beta:dedup:wamid.shared"
        assert captured_keys[0] != captured_keys[1]

    @pytest.mark.asyncio
    async def test_rate_limit_expire_set_on_first_request(self):
        """On first request (incr returns 1), expire is called with 60s window."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis):
            await WhatsAppWebhookService._check_rate_limit("alpha")

        mock_redis.expire.assert_called_once_with("alpha:rl:webhook", 60)
