import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [(AdminRole.viewer, 403), (AdminRole.admin_tenant, 200)])
async def test_operations_require_admin_role(role, expected):
    tenant_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "tenant_a", "A", "active", None)
    payload = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=role.value,
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    app.dependency_overrides[get_current_admin] = lambda: payload
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    try:
        with (
            patch(
                "app.core.middleware.TenantResolver.from_tenant_id_header",
                new=AsyncMock(return_value=tenant),
            ),
            patch(
                "app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/whatsapp/operations/events", headers={"X-Tenant-ID": str(tenant_id)}
                )
        assert response.status_code == expected
        if expected == 403:
            session.execute.assert_not_awaited()
        else:
            assert response.json()["events"] == []
            statement = session.execute.await_args.args[0]
            assert tenant_id in statement.compile().params.values()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [(AdminRole.viewer, 403), (AdminRole.admin_tenant, 200)])
async def test_review_requires_admin_and_records_audit(role, expected):
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "tenant_a", "A", "active", None)
    payload = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=role.value,
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    app.dependency_overrides[get_current_admin] = lambda: payload
    event = MagicMock(id=event_id, state="uncertain")
    result = MagicMock()
    result.scalar_one_or_none.return_value = event
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    session.add = MagicMock()
    try:
        with (
            patch(
                "app.core.middleware.TenantResolver.from_tenant_id_header",
                new=AsyncMock(return_value=tenant),
            ),
            patch(
                "app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/whatsapp/operations/events/{event_id}/review?kind=status",
                    headers={"X-Tenant-ID": str(tenant_id)},
                    json={"action": "follow_up"},
                )
        assert response.status_code == expected
        if expected == 403:
            session.execute.assert_not_awaited()
        else:
            assert response.json()["state"] == "follow_up"
            audit = session.add.call_args.args[0]
            assert audit.tenant_slug == tenant.slug and audit.details["decision"] == "follow_up"
            assert tenant_id in session.execute.await_args.args[0].compile().params.values()
            session.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
