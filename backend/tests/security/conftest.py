"""Shared fixtures for security tests.

Provides admin payloads for each role, a test tenant, and helpers
for dependency overrides.
"""

import os
import uuid

# Env vars must be set BEFORE importing app (which triggers Settings())
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload

TEST_TENANT_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TEST_ADMIN_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
OTHER_TENANT_ID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


def make_admin_payload(
    role: str = AdminRole.admin_tenant.value,
    tenant_id: uuid.UUID | None = TEST_TENANT_ID,
    admin_id: uuid.UUID | None = None,
    **overrides,
) -> AdminTokenPayload:
    """Create an AdminTokenPayload with sensible defaults."""
    defaults = {
        "sub": str(admin_id or TEST_ADMIN_ID),
        "role": role,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


@pytest.fixture
def super_admin_payload() -> AdminTokenPayload:
    return make_admin_payload(role=AdminRole.super_admin.value, tenant_id=None)


@pytest.fixture
def admin_tenant_payload() -> AdminTokenPayload:
    return make_admin_payload(role=AdminRole.admin_tenant.value, tenant_id=TEST_TENANT_ID)


@pytest.fixture
def supervisor_payload() -> AdminTokenPayload:
    return make_admin_payload(role=AdminRole.supervisor.value, tenant_id=TEST_TENANT_ID)


@pytest.fixture
def viewer_payload() -> AdminTokenPayload:
    return make_admin_payload(role=AdminRole.viewer.value, tenant_id=TEST_TENANT_ID)


@pytest.fixture
def test_tenant() -> TenantContext:
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="alpha",
        name="CRI Alpha",
        status="active",
        whatsapp_config={"phone_number_id": "111", "access_token": "tok_alpha"},
    )


def override_admin(payload: AdminTokenPayload):
    """Set get_current_admin dependency override. Returns cleanup function."""
    app.dependency_overrides[get_current_admin] = lambda: payload
    return lambda: app.dependency_overrides.pop(get_current_admin, None)


def mock_tenant_db_session(
    *,
    scalar_one_or_none=None,
    scalar_one=None,
    scalars_all=None,
    execute_side_effect=None,
):
    """Create a mock for TenantContext.db_session() async context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none
    mock_result.scalar_one.return_value = scalar_one or scalar_one_or_none

    if scalars_all is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_all
        mock_result.scalars.return_value = mock_scalars

    if execute_side_effect:
        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    return mock_session
