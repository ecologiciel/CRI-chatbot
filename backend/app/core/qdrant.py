"""Async Qdrant client.

All operations MUST target tenant's collection: kb_{tenant.slug}
"""

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings

_qdrant: AsyncQdrantClient | None = None


async def init_qdrant() -> AsyncQdrantClient:
    """Initialize Qdrant client."""
    global _qdrant  # noqa: PLW0603
    settings = get_settings()
    _qdrant = AsyncQdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
        grpc_port=settings.qdrant_grpc_port,
        prefer_grpc=True,
        timeout=10,
    )
    return _qdrant


def get_qdrant() -> AsyncQdrantClient:
    """Get the Qdrant client."""
    if _qdrant is None:
        raise RuntimeError("Qdrant not initialized. Call init_qdrant() in app lifespan.")
    return _qdrant


async def close_qdrant() -> None:
    """Close Qdrant connection."""
    global _qdrant  # noqa: PLW0603
    if _qdrant is not None:
        await _qdrant.close()
        _qdrant = None
