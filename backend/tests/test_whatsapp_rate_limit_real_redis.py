"""Rate-limit atomicity against an explicitly provided disposable Redis."""

import asyncio
import os
import uuid
from unittest.mock import patch

import pytest
from redis.asyncio import Redis

from app.core.tenant import TenantContext
from app.services.whatsapp.handler import USER_RATE_LIMIT_WINDOW, MessageHandler


@pytest.mark.asyncio
async def test_concurrent_limit_and_expiry_recovery():
    redis_url = os.getenv("TEST_WHATSAPP_RATE_REDIS_URL")
    if not redis_url:
        pytest.skip("requires disposable Redis")
    redis = Redis.from_url(redis_url, decode_responses=True)
    tenant = TenantContext(
        id=uuid.uuid4(), slug=f"test_{uuid.uuid4().hex}", name="Test", status="active",
        whatsapp_config={},
    )
    phone = "+212600000001"
    key = f"{tenant.redis_prefix}:rl:user:{phone}"
    try:
        with patch("app.services.whatsapp.handler.get_redis", return_value=redis):
            results = await asyncio.gather(*(
                MessageHandler._check_user_rate_limit(tenant, phone) for _ in range(25)
            ))
            assert results.count(False) == 10
            assert results.count(True) == 15
            assert await redis.get(key) == "25"
            assert 0 < await redis.ttl(key) <= USER_RATE_LIMIT_WINDOW

            # A pre-existing legacy key without a TTL must recover, without
            # resetting the count or granting another burst.
            await redis.set(key, 10)
            assert await MessageHandler._check_user_rate_limit(tenant, phone)
            assert await redis.get(key) == "11"
            assert 0 < await redis.ttl(key) <= USER_RATE_LIMIT_WINDOW

            # A normal existing window must not slide on every request.
            await redis.expire(key, 5)
            await MessageHandler._check_user_rate_limit(tenant, phone)
            assert 0 < await redis.ttl(key) <= 5
    finally:
        await redis.delete(key)
        await redis.aclose()
