"""Public session identifies the institution selected for the demo."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response

from app.api.v1.public_chat import create_session
from app.core.tenant import TenantContext


@pytest.mark.asyncio
async def test_public_session_returns_tenant_name():
    tenant = TenantContext(
        id=uuid.uuid4(),
        slug="prospect",
        name="Institution Exemple",
        status="active",
        whatsapp_config=None,
    )
    redis = AsyncMock()
    with (
        patch(
            "app.api.v1.public_chat._resolve_public_tenant", AsyncMock(return_value=(tenant, None))
        ),
        patch("app.api.v1.public_chat.get_redis", return_value=redis),
    ):
        response = await create_session("prospect", Response())
    assert response.tenant_name == "Institution Exemple"
    assert response.tenant_slug == "prospect"
    redis.setex.assert_awaited_once()
