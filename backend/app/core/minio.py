"""Async MinIO (S3-compatible) client.

All operations MUST target tenant's bucket: cri-{tenant.slug}
"""

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
