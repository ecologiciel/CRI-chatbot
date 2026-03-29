"""Audit trail middleware — captures mutating HTTP requests automatically.

Fires audit log entries asynchronously (fire-and-forget) to avoid
blocking the HTTP response. Only POST/PUT/PATCH/DELETE are captured.

Excluded paths: webhooks (too voluminous), health checks, docs, metrics.
Login/logout are captured with specific action overrides.
"""

from __future__ import annotations

import asyncio
import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.schemas.audit import AuditLogCreate
from app.services.audit import get_audit_service

logger = structlog.get_logger()

# --- Constants ---

AUDITED_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

AUDIT_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/api/v1/webhook/",
    "/api/v1/health",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",
)

_METHOD_ACTION_MAP: dict[str, str] = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# Matches standard UUID format in URL path segments
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _extract_resource_type(path: str) -> str:
    """Extract resource type from API path.

    Example: /api/v1/contacts/abc-123 → "contacts"
             /api/v1/kb/documents    → "kb"

    Args:
        path: The HTTP request path.

    Returns:
        Resource type string, or the full path if not parseable.
    """
    parts = path.strip("/").split("/")
    # /api/v1/{resource_type}/...
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
        return parts[2]
    return path


def _extract_resource_id(path: str) -> str | None:
    """Extract UUID resource ID from URL path if present.

    Args:
        path: The HTTP request path.

    Returns:
        UUID string if found, else None.
    """
    match = _UUID_PATTERN.search(path)
    return match.group(0) if match else None


def _extract_user_from_token(request: Request) -> tuple[uuid.UUID | None, str]:
    """Extract user_id from JWT Authorization header (lightweight, no DB call).

    Args:
        request: The HTTP request.

    Returns:
        Tuple of (user_id or None, user_type).
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "system"

    try:
        # Import here to avoid circular imports at module level
        from app.services.auth.jwt import JWTManager

        token = auth_header[7:]  # Strip "Bearer "
        payload = JWTManager.verify_token(token)
        sub = payload.get("sub")
        if sub:
            return uuid.UUID(sub), "admin"
    except Exception:
        # Invalid/expired token — not an error for audit purposes
        pass

    return None, "system"


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware that auto-captures mutating HTTP requests in the audit trail.

    Intercepts POST/PUT/PATCH/DELETE requests (excluding webhooks, health,
    docs) and logs them asynchronously via AuditService.

    Admin identity is extracted from the JWT token (lightweight decode,
    no DB verification). Tenant is read from request.state.tenant
    (set by TenantMiddleware).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        """Process request and fire audit log for mutating methods."""
        # Only audit mutating methods
        if request.method not in AUDITED_METHODS:
            return await call_next(request)

        path = request.url.path

        # Skip excluded paths
        if any(path.startswith(prefix) for prefix in AUDIT_EXCLUDED_PREFIXES):
            return await call_next(request)

        # Execute the request
        response = await call_next(request)

        # --- Build audit entry (post-response) ---
        try:
            # Tenant context (set by TenantMiddleware, may be absent)
            tenant = getattr(request.state, "tenant", None)
            tenant_slug = tenant.slug if tenant else "system"

            # User identity from JWT (lightweight decode)
            user_id, user_type = _extract_user_from_token(request)

            # Resource info from path
            resource_type = _extract_resource_type(path)
            resource_id = _extract_resource_id(path)

            # Action — override for auth endpoints
            if "/auth/login" in path:
                action = "login"
            elif "/auth/logout" in path:
                action = "logout"
            else:
                action = _METHOD_ACTION_MAP.get(request.method, request.method.lower())

            audit_data = AuditLogCreate(
                tenant_slug=tenant_slug,
                user_id=user_id,
                user_type=user_type,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "")[:512] or None,
            )

            # Fire-and-forget — do not await, do not block the response
            asyncio.create_task(_fire_audit(audit_data))

        except Exception as exc:
            # Audit middleware must NEVER crash the request
            logger.error(
                "audit_middleware_error",
                error=str(exc),
                path=path,
                method=request.method,
                exc_info=True,
            )

        return response


async def _fire_audit(data: AuditLogCreate) -> None:
    """Execute the audit log write (called via asyncio.create_task)."""
    service = get_audit_service()
    await service.log_action(data)
