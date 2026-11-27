"""Async MinIO (S3-compatible) client.

All operations MUST target tenant's bucket: cri-{tenant.slug}
"""

import asyncio

import aiohttp
from miniopy_async import Minio

from app.core.config import get_settings

_minio: Minio | None = None


def init_minio() -> Minio:
    """Initialize MinIO client."""
    global _minio  # noqa: PLW0603
    settings = get_settings()
    _minio = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_use_ssl,
    )
    return _minio


def get_minio() -> Minio:
    """Get the MinIO client."""
    if _minio is None:
        raise RuntimeError("MinIO not initialized. Call init_minio() in app lifespan.")
    return _minio


async def get_object_bytes(
    bucket_name: str, object_name: str, *, max_bytes: int | None = None
) -> bytes:
    """Read an object while owning the aiohttp session required by miniopy_async."""
    if max_bytes is not None and max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    async with aiohttp.ClientSession() as session:
        response = await get_minio().get_object(bucket_name, object_name, session)
        try:
            if max_bytes is None:
                return await response.read()
            try:
                content = await response.content.readexactly(max_bytes + 1)
            except asyncio.IncompleteReadError as exc:
                content = exc.partial
            if len(content) > max_bytes:
                raise ValueError("Object exceeds maximum size")
            return content
        finally:
            response.release()
