"""RBAC dependencies for FastAPI endpoints.

get_current_admin: verifies Bearer token, checks admin still active, returns AdminTokenPayload.
require_role: factory that checks admin role is in the allowed set.

Usage:
    @router.get("/protected")
    async def protected_endpoint(
        admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin)),
    ):
        ...
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.models.admin import Admin
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload
from app.services.auth.service import AuthService

logger = structlog.get_logger()

# auto_error=False so we raise our own AuthenticationError
# (caught by the global CRIBaseException handler → consistent JSON format)
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AdminTokenPayload:
    """Extract and verify admin from JWT Bearer token.

    Also verifies that the admin account is still active in DB
    and that the session is valid (IP unchanged, not superseded).

    Args:
        request: Current HTTP request (for client IP extraction).
        credentials: Extracted from Authorization header by HTTPBearer.

    Returns:
        Validated AdminTokenPayload with sub, role, tenant_id.

    Raises:
        AuthenticationError: Missing/invalid token or inactive account.
    """
    if credentials is None:
        raise AuthenticationError("Missing authentication token")

    ip_address = request.client.host if request.client else None

    auth_service = AuthService()
    payload = await auth_service.verify_access_token(credentials.credentials, ip_address=ip_address)

    # Verify admin still active in DB (token could outlive deactivation)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Admin.id).where(
                Admin.id == uuid.UUID(payload.sub),
                Admin.is_active.is_(True),
            )
        )
        if result.scalar_one_or_none() is None:
            logger.warning(
                "token_for_inactive_admin",
                admin_id=payload.sub,
                role=payload.role,
            )
            raise AuthenticationError("Admin account is no longer active")

    return payload


def require_role(*roles: AdminRole):
    """Factory returning a dependency that checks the admin's role.

    Args:
        *roles: Allowed AdminRole values for this endpoint.

    Returns:
        A FastAPI dependency function.

    Usage:
        Depends(require_role(AdminRole.super_admin))
        Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant))
    """

    async def _check_role(
        admin: AdminTokenPayload = Depends(get_current_admin),
    ) -> AdminTokenPayload:
        if AdminRole(admin.role) not in roles:
            raise AuthorizationError(
                f"Role '{admin.role}' is not authorized for this operation",
                details={"required_roles": [r.value for r in roles]},
            )
        return admin

    return _check_role
