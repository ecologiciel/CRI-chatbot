"""Account updates must preserve the tenant assignment boundary."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.admins import update_admin
from app.core.exceptions import ValidationError
from app.models.enums import AdminRole, TenantStatus
from app.schemas.admin import AdminUpdate
from app.schemas.auth import AdminTokenPayload


@pytest.fixture
def context():
    tenant_id = uuid.uuid4()
    target = SimpleNamespace(
        id=uuid.uuid4(),
        email="test@example.com",
        full_name="Test",
        role=AdminRole.viewer,
        tenant_id=tenant_id,
        is_active=False,
        last_login=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    caller = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role="super_admin",
        tenant_id=None,
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = MagicMock(
        all=lambda: [SimpleNamespace(id=tenant_id, status=TenantStatus.inactive)]
    )
    return target, caller, session


@pytest.mark.asyncio
async def test_reactivation_of_inactive_tenant_rejected(context):
    target, caller, session = context
    with (
        patch("app.api.v1.admins.get_session_factory", return_value=lambda: session),
        patch("app.api.v1.admins._get_admin_in_tenant", AsyncMock(return_value=target)),
    ):
        with pytest.raises(ValidationError, match="institution inactive"):
            await update_admin(target.id, AdminUpdate(is_active=True), caller)
    assert target.is_active is False
    session.commit.assert_not_awaited()
    assert "FOR UPDATE" in str(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_super_admin_cannot_remain_bound_to_tenant(context):
    target, caller, session = context
    with (
        patch("app.api.v1.admins.get_session_factory", return_value=lambda: session),
        patch("app.api.v1.admins._get_admin_in_tenant", AsyncMock(return_value=target)),
    ):
        with pytest.raises(ValidationError, match="super-administrateur"):
            await update_admin(target.id, AdminUpdate(role=AdminRole.super_admin), caller)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_account_change_requires_retry(context):
    target, caller, session = context

    async def change_during_lock(*args, **kwargs):
        target.tenant_id = None

    session.refresh.side_effect = change_during_lock
    with (
        patch("app.api.v1.admins.get_session_factory", return_value=lambda: session),
        patch("app.api.v1.admins._get_admin_in_tenant", AsyncMock(return_value=target)),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_admin(target.id, AdminUpdate(is_active=True), caller)
    assert exc.value.status_code == 409
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_null_role_rejected(context):
    target, caller, session = context
    with (
        patch("app.api.v1.admins.get_session_factory", return_value=lambda: session),
        patch("app.api.v1.admins._get_admin_in_tenant", AsyncMock(return_value=target)),
    ):
        with pytest.raises(ValidationError, match="role"):
            await update_admin(target.id, AdminUpdate(role=None), caller)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reactivation_of_active_tenant_succeeds(context):
    target, caller, session = context
    session.execute.return_value = MagicMock(
        all=lambda: [SimpleNamespace(id=target.tenant_id, status=TenantStatus.active)]
    )
    with (
        patch("app.api.v1.admins.get_session_factory", return_value=lambda: session),
        patch("app.api.v1.admins._get_admin_in_tenant", AsyncMock(return_value=target)),
    ):
        response = await update_admin(target.id, AdminUpdate(is_active=True), caller)
    assert response.is_active is True
    session.commit.assert_awaited_once()
