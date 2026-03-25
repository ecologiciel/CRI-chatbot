"""Async Redis client.

All keys MUST be prefixed with tenant slug. See multi-tenant-patterns skill.
Usage: redis = get_redis(); await redis.get(f"{tenant.slug}:session:{id}")
"""

import redis.asyncio as aioredis

from app.core.config import get_settings

_redis: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Initialize Redis connection."""
    global _redis  # noqa: PLW0603
    settings = get_settings()
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        retry_on_timeout=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    return _redis


def get_redis() -> aioredis.Redis:
    """Get the Redis client. Must call init_redis() first (in lifespan)."""
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() in app lifespan.")
    return _redis


async def close_redis() -> None:
    """Close Redis connection. Called on app shutdown."""
    global _redis  # noqa: PLW0603
    if _redis is not None:
        await _redis.close()
        _redis = None
