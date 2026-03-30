"""Authentication API endpoints — login, refresh, logout, me.

/login and /refresh are unauthenticated (excluded from TenantMiddleware).
/me and /logout require a valid Bearer access token.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.exceptions import AuthenticationError
from app.core.rbac import get_current_admin
from app.models.admin import Admin
from app.schemas.admin import AdminResponse
from app.schemas.auth import (
    AdminTokenPayload,
    AuthTokenResponse,
    LoginRequest,
    RefreshTokenRequest,
)
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthTokenResponse)
async def login(data: LoginRequest, request: Request) -> AuthTokenResponse:
    """Authenticate admin and return JWT token pair.

    No tenant context required — admins table is in public schema.
    Passes client IP for advanced session tracking (Phase 2).

    Raises:
        AuthenticationError (401): Invalid credentials.
        AccountLockedError (429): Too many failed attempts.
    """
    service = AuthService()
    ip_address = request.client.host if request.client else None
    return await service.login(data.email, data.password, ip_address=ip_address)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(data: RefreshTokenRequest) -> AuthTokenResponse:
    """Rotate refresh token and get new token pair.

    Single-use: the old refresh token is invalidated on use.

    Raises:
        AuthenticationError (401): Invalid, expired, or already-used token.
    """
    service = AuthService()
    return await service.refresh_token(data.refresh_token)


@router.get("/me", response_model=AdminResponse)
async def get_me(
    admin: AdminTokenPayload = Depends(get_current_admin),
) -> AdminResponse:
    """Get the authenticated admin's profile.

    Fetches fresh data from DB (not just token claims) so changes
    to name, role, etc. are reflected immediately.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Admin).where(Admin.id == uuid.UUID(admin.sub)))
        db_admin = result.scalar_one_or_none()

    if not db_admin:
        raise AuthenticationError("Admin account not found")

    return AdminResponse.model_validate(db_admin)


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    data: RefreshTokenRequest,
    admin: AdminTokenPayload = Depends(get_current_admin),
) -> Response:
    """Invalidate a refresh token.

    Requires both a valid access token (Bearer header) and the
    refresh token to invalidate (in the request body).

    Args:
        data: Contains the refresh_token to invalidate.
        admin: Verified from Bearer token (defense-in-depth).
    """
    # Decode refresh token to extract jti
    payload = JWTManager.verify_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise AuthenticationError("Invalid token type: expected refresh token")

    jti = payload.get("jti")
    if not jti:
        raise AuthenticationError("Invalid token: missing jti")

    service = AuthService()
    await service.logout(jti, admin_id=admin.sub)

    logger.info("admin_logout", admin_id=admin.sub)
    return Response(status_code=204)
