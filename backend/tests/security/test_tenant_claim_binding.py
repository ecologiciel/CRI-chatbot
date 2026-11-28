"""The requested tenant and current account must agree with JWT claims."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions import AuthorizationError
from app.core.rbac import get_current_admin
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,matching,allowed",
    [
        (AdminRole.admin_tenant, True, True),
        (AdminRole.admin_tenant, False, False),
        (AdminRole.viewer, False, False),
        (AdminRole.super_admin, False, True),
    ],
)
async def test_account_cannot_switch_tenant(role, matching, allowed):
    account_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    target_id = tenant_id if matching else uuid.uuid4()
    payload = AdminTokenPayload(
        sub=str(account_id),
        role=role.value,
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    request = SimpleNamespace(
        client=None, state=SimpleNamespace(tenant=SimpleNamespace(id=target_id))
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test")
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.scalar_one_or_none.return_value = account_id
    session.execute.return_value = result
    factory = MagicMock(return_value=session)
    auth = AsyncMock()
    auth.verify_access_token.return_value = payload
    with (
        patch("app.core.rbac.AuthService", return_value=auth),
        patch("app.core.rbac.get_session_factory", return_value=factory),
    ):
        if allowed:
            assert await get_current_admin(request, credentials) == payload
        else:
            with pytest.raises(AuthorizationError):
                await get_current_admin(request, credentials)
    query = session.execute.await_args.args[0]
    assert "admins.role" in str(query) and "admins.tenant_id" in str(query)


@pytest.mark.asyncio
async def test_websocket_rejects_other_tenant_before_subscription():
    from app.api.ws.escalation_ws import escalation_ws_endpoint

    admin = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=AdminRole.admin_tenant.value,
        tenant_id=str(uuid.uuid4()),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    websocket = AsyncMock()
    websocket.client = SimpleNamespace(host="127.0.0.1")
    websocket.receive_text.return_value = '{"type":"auth","token":"synthetic"}'
    tenant = SimpleNamespace(id=uuid.uuid4())
    with (
        patch("app.api.ws.escalation_ws.AuthService.verify_access_token", AsyncMock(return_value=admin)),
        patch("app.api.ws.escalation_ws.TenantResolver.from_tenant_id_header", AsyncMock(return_value=tenant)),
        patch(
            "app.api.ws.escalation_ws.ensure_admin_access",
            AsyncMock(side_effect=AuthorizationError("denied")),
        ) as check,
        patch("app.api.ws.escalation_ws.ws_manager") as manager,
    ):
        await escalation_ws_endpoint(websocket, str(tenant.id))
    check.assert_awaited_once_with(admin, tenant.id)
    websocket.close.assert_awaited_once_with(code=4003, reason="Insufficient permissions")
    manager.connect.assert_not_called()
