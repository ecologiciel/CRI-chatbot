"""API contract for the disabled-by-default durable agent reply path."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload
from app.services.escalation.reply_outbox import RegisteredReply


@pytest.mark.asyncio
@pytest.mark.parametrize("role,enabled,created,expected", [
    (AdminRole.viewer, True, True, 403),
    (AdminRole.admin_tenant, False, True, 503),
    (AdminRole.supervisor, True, True, 202),
    (AdminRole.supervisor, True, False, 200),
])
async def test_create_reply_requires_role_flag_and_stable_key(role, enabled, created, expected):
    tenant_id, actor_id, escalation_id, key, event_id = (uuid.uuid4() for _ in range(5))
    tenant = TenantContext(tenant_id, "fixture_api", "Fixture", "active", None)
    payload = AdminTokenPayload(sub=str(actor_id), role=role.value, tenant_id=str(tenant_id),
                                exp=9999999999, iat=1700000000, jti=str(uuid.uuid4()), type="access")
    app.dependency_overrides[get_current_admin] = lambda: payload
    try:
        with (patch("app.core.middleware.TenantResolver.from_tenant_id_header", new=AsyncMock(return_value=tenant)),
              patch("app.api.v1.escalation.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=enabled, kms_master_key="fixture")),
              patch("app.api.v1.escalation.get_redis", return_value=MagicMock(exists=AsyncMock(return_value=True))),
              patch("app.api.v1.escalation.VersionedEnvelopeService"),
              patch("app.api.v1.escalation.register_agent_reply", new=AsyncMock(return_value=RegisteredReply(event_id, "pending", created))) as register):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(f"/api/v1/escalations/{escalation_id}/reply-requests", headers={"X-Tenant-ID": str(tenant_id)}, json={"request_key": str(key), "message": "fixture"})
        assert response.status_code == expected
        if expected in {200, 202}:
            assert response.json() == {"id": str(event_id), "state": "pending", "created": created}
            assert register.await_args.args == (tenant, escalation_id, actor_id, key, "fixture")
        else:
            register.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, RuntimeError("fixture")])
async def test_reply_intake_fails_closed_if_worker_presence_is_missing(failure):
    tenant_id, actor_id, escalation_id, key = (uuid.uuid4() for _ in range(4))
    tenant = TenantContext(tenant_id, "fixture_api", "Fixture", "active", None)
    payload = AdminTokenPayload(sub=str(actor_id), role="admin_tenant", tenant_id=str(tenant_id),
                                exp=9999999999, iat=1700000000, jti=str(uuid.uuid4()), type="access")
    app.dependency_overrides[get_current_admin] = lambda: payload
    exists = AsyncMock(side_effect=failure) if isinstance(failure, Exception) else AsyncMock(return_value=failure)
    try:
        with (patch("app.core.middleware.TenantResolver.from_tenant_id_header", new=AsyncMock(return_value=tenant)),
              patch("app.api.v1.escalation.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=True)),
              patch("app.api.v1.escalation.get_redis", return_value=MagicMock(exists=exists)),
              patch("app.api.v1.escalation.register_agent_reply") as register):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(f"/api/v1/escalations/{escalation_id}/reply-requests", headers={"X-Tenant-ID": str(tenant_id)}, json={"request_key": str(key), "message": "fixture"})
        assert response.status_code == 503
        register.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_legacy_send_is_disabled_during_durable_cutover():
    tenant_id, actor_id, escalation_id = (uuid.uuid4() for _ in range(3))
    tenant = TenantContext(tenant_id, "fixture_api", "Fixture", "active", None)
    payload = AdminTokenPayload(sub=str(actor_id), role="admin_tenant", tenant_id=str(tenant_id),
                                exp=9999999999, iat=1700000000, jti=str(uuid.uuid4()), type="access")
    app.dependency_overrides[get_current_admin] = lambda: payload
    try:
        with (patch("app.core.middleware.TenantResolver.from_tenant_id_header", new=AsyncMock(return_value=tenant)),
              patch("app.api.v1.escalation.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=True)),
              patch("app.api.v1.escalation.get_escalation_service") as service):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(f"/api/v1/escalations/{escalation_id}/respond", headers={"X-Tenant-ID": str(tenant_id)}, json={"message": "fixture"})
        assert response.status_code == 409
        service.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reply_status_query_is_scoped_to_tenant_escalation_and_actor():
    tenant_id, actor_id, escalation_id, key, event_id = (uuid.uuid4() for _ in range(5))
    tenant = TenantContext(tenant_id, "fixture_api", "Fixture", "active", None)
    payload = AdminTokenPayload(sub=str(actor_id), role="supervisor", tenant_id=str(tenant_id),
                                exp=9999999999, iat=1700000000, jti=str(uuid.uuid4()), type="access")
    app.dependency_overrides[get_current_admin] = lambda: payload
    event = MagicMock(id=event_id, state="uncertain", outcome_code="provider_unconfirmed",
                      created_at=datetime.now(UTC), redacted_at=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = event
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    try:
        with (patch("app.core.middleware.TenantResolver.from_tenant_id_header", new=AsyncMock(return_value=tenant)),
              patch("app.api.v1.escalation.get_session_factory", return_value=lambda: session)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"/api/v1/escalations/{escalation_id}/reply-requests/{key}", headers={"X-Tenant-ID": str(tenant_id)})
        assert response.status_code == 200
        assert response.json()["state"] == "uncertain"
        params = session.execute.await_args.args[0].compile().params.values()
        assert all(value in params for value in (tenant_id, actor_id, escalation_id, key))
        assert "content" not in response.json()
    finally:
        app.dependency_overrides.clear()
