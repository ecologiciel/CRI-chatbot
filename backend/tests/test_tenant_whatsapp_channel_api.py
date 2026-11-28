"""Channel configuration is privileged and credential-safe on validation failure."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.v1.tenant import router
from app.core.exceptions import AuthorizationError, CRIBaseException
from app.core.rbac import get_current_admin
from app.main import app
from app.models.enums import AdminRole


@pytest.mark.asyncio
async def test_channel_configuration_requires_super_admin():
    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == "/tenants/{tenant_id}/whatsapp-channel")
    dependency = next(d.call for d in route.dependant.dependencies if d.name == "admin")
    with pytest.raises(AuthorizationError):
        await dependency(admin=SimpleNamespace(role=AdminRole.admin_tenant.value))
    admin = SimpleNamespace(role=AdminRole.super_admin.value)
    assert await dependency(admin=admin) is admin


@pytest.mark.asyncio
async def test_invalid_channel_payload_never_reflects_credentials():
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(role=AdminRole.super_admin.value, sub=str(uuid.uuid4()))
    body = {"phone_number_id": {"private": "synthetic-nested-secret"}, "access_token": "synthetic-access-secret", "verify_token": "synthetic-verify-secret", "app_secret": "synthetic-app-secret"}
    try:
        with patch("app.core.audit_middleware._fire_audit", new=AsyncMock(return_value=True)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.put(f"/api/v1/tenants/{uuid.uuid4()}/whatsapp-channel", json=body)
        assert response.status_code == 422
        assert "synthetic-" not in response.text
    finally:
        app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_webhook_error_logs_exclude_query_credentials():
    logger = MagicMock()
    params = {"hub.mode": "subscribe", "hub.verify_token": "synthetic-private-token", "hub.challenge": "challenge"}
    with (
        patch("app.main.logger", logger),
        patch("app.api.v1.webhook._require_proxy_secret"),
        patch("app.api.v1.webhook.webhook_service.verify_webhook", side_effect=CRIBaseException("fixture")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/api/v1/webhook/whatsapp", params=params)
    assert logger.warning.call_args.kwargs["path"] == "/api/v1/webhook/whatsapp"
    assert "synthetic-private-token" not in str(logger.warning.call_args)
