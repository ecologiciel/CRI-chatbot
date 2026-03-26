"""ARQ (async Redis queue) connection pool for task enqueueing.

The pool is initialized in the FastAPI lifespan and shared across requests.
Workers use their own Redis connection via WorkerSettings.

Usage:
    pool = get_arq_pool()
    await pool.enqueue_job("ingest_document_task", tenant_slug, document_id)
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_arq_pool: ArqRedis | None = None


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app config."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


async def init_arq_pool() -> ArqRedis:
    """Initialize the ARQ connection pool. Called in FastAPI lifespan."""
    global _arq_pool  # noqa: PLW0603
    _arq_pool = await create_pool(_get_redis_settings())
    return _arq_pool


def get_arq_pool() -> ArqRedis:
    """Get the ARQ pool. Raises if not initialized."""
    if _arq_pool is None:
        raise RuntimeError("ARQ pool not initialized. Call init_arq_pool() in app lifespan.")
    return _arq_pool


async def close_arq_pool() -> None:
    """Close the ARQ pool. Called on app shutdown."""
    global _arq_pool  # noqa: PLW0603
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
