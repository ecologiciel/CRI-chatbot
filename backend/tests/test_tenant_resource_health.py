"""Resource presence must not be confused with provider connectivity."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.tenant import tenant_resource_health
from app.models.enums import TenantStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("qdrant_down,minio_down", [(False, False), (True, False), (False, True)])
async def test_health_reports_resource_presence_without_secrets(qdrant_down, minio_down):
    tenant = SimpleNamespace(
        id=uuid.uuid4(),
        name="Institution",
        slug="alpha",
        status=TenantStatus.active,
        public_config={"web_enabled": True},
        whatsapp_config={"phone_number_id": "123", "access_token": "secret-value"},
    )
    count = MagicMock()
    count.scalar_one.return_value = 1
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [tenant]
    namespaces = MagicMock()
    namespaces.scalars.return_value.all.return_value = ["tenant_alpha"]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[count, rows, namespaces]))

    @asynccontextmanager
    async def factory():
        yield db

    qdrant = SimpleNamespace(get_collections=AsyncMock())
    if qdrant_down:
        qdrant.get_collections.side_effect = RuntimeError("secret internal error")
    else:
        qdrant.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="kb_alpha")]
        )
    minio = SimpleNamespace(
        list_buckets=AsyncMock(return_value=[SimpleNamespace(name="cri-alpha")])
    )
    if minio_down:
        minio.list_buckets.side_effect = RuntimeError("secret internal error")
    with (
        patch("app.api.v1.tenant.get_session_factory", return_value=factory),
        patch("app.api.v1.tenant.get_qdrant", return_value=qdrant),
        patch("app.api.v1.tenant.get_minio", return_value=minio),
    ):
        response = await tenant_resource_health(admin=MagicMock(), page=1, page_size=20)
    item = response["items"][0]
    assert item["schema_present"] is True
    assert item["bucket_present"] is (None if minio_down else True)
    assert item["collection_present"] is (None if qdrant_down else True)
    assert item["whatsapp_configured"] is True
    assert "secret" not in str(response)
    assert "whatsapp_connected" not in item


@pytest.mark.asyncio
async def test_monitoring_route_requires_super_admin():
    from fastapi.routing import APIRoute

    from app.api.v1.tenant import router
    from app.core.exceptions import AuthorizationError
    from app.models.enums import AdminRole

    route = next(
        r for r in router.routes if isinstance(r, APIRoute) and r.path == "/tenants/health"
    )
    dependency = next(d.call for d in route.dependant.dependencies if d.name == "admin")
    with pytest.raises(AuthorizationError):
        await dependency(admin=SimpleNamespace(role=AdminRole.admin_tenant.value))
    payload = SimpleNamespace(role=AdminRole.super_admin.value)
    assert await dependency(admin=payload) is payload
