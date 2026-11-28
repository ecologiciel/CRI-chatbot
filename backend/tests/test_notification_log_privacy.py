"""Malformed notification events must not disclose citizen data in logs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.notification import _process_tenant_notifications, _send_with_retry


@pytest.mark.asyncio
async def test_retry_failure_does_not_log_exception_contents():
    secret = "fixture-sensitive-dossier-123"
    service = MagicMock(send_notification=AsyncMock(side_effect=ValueError(secret)))
    logger = MagicMock()
    with patch("app.workers.notification.asyncio.sleep", new=AsyncMock()):
        result = await _send_with_retry(service, object(), object(), logger)
    assert secret not in repr(result)
    assert secret not in repr(logger.mock_calls)
    assert result == {"status": "failed", "error_type": "ValueError"}


@pytest.mark.asyncio
async def test_malformed_queue_payload_is_not_logged():
    secret = "fixture-sensitive-identifier"
    pipeline = MagicMock()
    pipeline.execute = AsyncMock(side_effect=[[[f'{{"identifier":"{secret}"}}']], [[]]])
    redis = MagicMock(pipeline=MagicMock(return_value=pipeline))
    logger = MagicMock()
    tenant = MagicMock(slug="fixture")
    with (
        patch("app.core.tenant.TenantResolver.from_slug", new=AsyncMock(return_value=tenant)),
        patch("app.core.redis.get_redis", return_value=redis),
        patch("app.workers.notification.logger.bind", return_value=logger),
    ):
        stats = await _process_tenant_notifications("fixture")
    assert stats["failed"] == 1
    assert secret not in repr(logger.mock_calls)
