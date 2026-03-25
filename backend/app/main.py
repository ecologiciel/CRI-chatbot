"""FastAPI application entrypoint.

Lifespan manages startup/shutdown of all service connections.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.database import close_engine, get_engine
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CRIBaseException,
    DuplicateResourceError,
    RateLimitExceededError,
    ResourceNotFoundError,
    TenantInactiveError,
    TenantNotFoundError,
    TenantResolutionError,
    ValidationError,
)
from app.core.logging import setup_logging
from app.core.middleware import TenantMiddleware
from app.core.minio import init_minio
from app.core.qdrant import close_qdrant, init_qdrant
from app.core.redis import close_redis, init_redis

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup and shutdown logic."""
    # --- Startup ---
    setup_logging()
    settings = get_settings()
    logger.info("starting_application", environment=settings.environment)

    # Initialize connections (order matters)
    get_engine()  # SQLAlchemy engine (lazy, but validates URL)
    logger.info("database_engine_created")

    await init_redis()
    logger.info("redis_connected")

    await init_qdrant()
    logger.info("qdrant_connected")

    init_minio()
    logger.info("minio_connected")

    logger.info("application_started", environment=settings.environment)

    yield  # Application runs here

    # --- Shutdown ---
    logger.info("shutting_down_application")
    await close_qdrant()
    await close_redis()
    await close_engine()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="CRI Chatbot Platform API",
        description=(
            "Multi-tenant RAG chatbot platform for "
            "Centres Régionaux d'Investissement du Maroc"
        ),
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.backoffice_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Tenant-ID"],
    )

    # --- Tenant resolution middleware ---
    app.add_middleware(TenantMiddleware)

    # --- Prometheus metrics ---
    Instrumentator(
        should_group_status_codes=True,
        should_group_untemplated=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics")

    # --- Exception handlers ---
    @app.exception_handler(CRIBaseException)
    async def cri_exception_handler(
        request: Request, exc: CRIBaseException
    ) -> JSONResponse:
        logger.warning(
            "cri_exception",
            error_type=type(exc).__name__,
            message=exc.message,
            details=exc.details,
            path=str(request.url),
        )
        status_code = _get_status_code(exc)
        return JSONResponse(
            status_code=status_code,
            content={
                "error": type(exc).__name__,
                "message": exc.message,
                "details": exc.details,
            },
        )

    # --- Routes ---
    app.include_router(health_router, prefix="/api/v1", tags=["health"])

    return app


def _get_status_code(exc: CRIBaseException) -> int:
    """Map exception types to HTTP status codes."""
    mapping: dict[type[CRIBaseException], int] = {
        TenantResolutionError: 400,
        AuthenticationError: 401,
        AuthorizationError: 403,
        TenantInactiveError: 403,
        TenantNotFoundError: 404,
        ResourceNotFoundError: 404,
        DuplicateResourceError: 409,
        ValidationError: 422,
        RateLimitExceededError: 429,
    }
    return mapping.get(type(exc), 500)


app = create_app()
