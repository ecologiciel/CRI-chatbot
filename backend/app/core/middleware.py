"""HTTP middleware stack for the CRI platform.

TenantMiddleware: resolves tenant from X-Tenant-ID header on every
non-excluded request and injects TenantContext into request.state.
"""

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.exceptions import TenantInactiveError, TenantNotFoundError
from app.core.tenant import TenantResolver

logger = structlog.get_logger()

# Paths that do NOT require tenant resolution
TENANT_EXCLUDED_PATHS: set[str] = {
    "/health",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/metrics",
}

# Path prefixes that do NOT require tenant resolution
# - webhooks: resolve tenant from payload, not header
# - auth: operates on public.admins (global, not tenant-scoped)
# - tenants: operates on public.tenants (management endpoints use JWT auth, not X-Tenant-ID)
TENANT_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/api/v1/webhook/",
    "/api/v1/auth/",
    "/api/v1/tenants",
    "/ws/",  # WebSocket endpoints handle tenant resolution internally
)


class TenantMiddleware(BaseHTTPMiddleware):
    """Resolve tenant from X-Tenant-ID header and inject into request.state.

    For excluded paths (health, docs, webhooks), the request passes through
    without tenant resolution. All other routes require the header.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        path = request.url.path

        # Skip excluded paths
        if path in TENANT_EXCLUDED_PATHS or any(
            path.startswith(prefix) for prefix in TENANT_EXCLUDED_PREFIXES
        ):
            return await call_next(request)

        # Extract tenant ID from header
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            logger.warning("missing_tenant_header", path=path, method=request.method)
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Tenant-ID header is required"},
            )

        # Resolve tenant
        try:
            tenant_context = await TenantResolver.from_tenant_id_header(tenant_id)
            request.state.tenant = tenant_context
            logger.info(
                "tenant_resolved",
                tenant_slug=tenant_context.slug,
                path=path,
                method=request.method,
            )
        except TenantNotFoundError as exc:
            logger.warning(
                "tenant_not_found",
                identifier=tenant_id,
                path=path,
            )
            return JSONResponse(
                status_code=404,
                content={"detail": exc.message},
            )
        except TenantInactiveError as exc:
            logger.warning(
                "tenant_inactive",
                identifier=tenant_id,
                path=path,
                details=exc.details,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": exc.message},
            )
        except Exception as exc:
            logger.error(
                "tenant_resolution_failed",
                identifier=tenant_id,
                path=path,
                error=str(exc),
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error during tenant resolution"},
            )

        return await call_next(request)
