"""Health check endpoint.

Verifies connectivity to ALL infrastructure services.
Used by Docker health check and monitoring.
"""

import time

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.database import get_engine
from app.core.minio import get_minio
from app.core.qdrant import get_qdrant
from app.core.redis import get_redis

router = APIRouter()
logger = structlog.get_logger()


class ServiceHealth(BaseModel):
    status: str  # "ok" | "error"
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str = "0.1.0"
    services: dict[str, ServiceHealth]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check connectivity to all infrastructure services."""
    services: dict[str, ServiceHealth] = {}

    # PostgreSQL
    try:
        start = time.monotonic()
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000
        services["postgresql"] = ServiceHealth(status="ok", latency_ms=round(latency, 2))
    except Exception as e:
        services["postgresql"] = ServiceHealth(status="error", error=str(e)[:200])

    # Redis
    try:
        start = time.monotonic()
        redis = get_redis()
        await redis.ping()
        latency = (time.monotonic() - start) * 1000
        services["redis"] = ServiceHealth(status="ok", latency_ms=round(latency, 2))
    except Exception as e:
        services["redis"] = ServiceHealth(status="error", error=str(e)[:200])

    # Qdrant
    try:
        start = time.monotonic()
        qdrant = get_qdrant()
        await qdrant.get_collections()
        latency = (time.monotonic() - start) * 1000
        services["qdrant"] = ServiceHealth(status="ok", latency_ms=round(latency, 2))
    except Exception as e:
        services["qdrant"] = ServiceHealth(status="error", error=str(e)[:200])

    # MinIO
    try:
        start = time.monotonic()
        minio = get_minio()
        await minio.list_buckets()
        latency = (time.monotonic() - start) * 1000
        services["minio"] = ServiceHealth(status="ok", latency_ms=round(latency, 2))
    except Exception as e:
        services["minio"] = ServiceHealth(status="error", error=str(e)[:200])

    # Overall status
    error_count = sum(1 for s in services.values() if s.status == "error")
    if error_count == 0:
        overall = "healthy"
    elif error_count < len(services):
        overall = "degraded"
    else:
        overall = "unhealthy"

    return HealthResponse(status=overall, services=services)
