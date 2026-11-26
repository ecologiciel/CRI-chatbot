"""Public session identifies the institution selected for the demo."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response

from app.api.v1.public_chat import create_session, send_message
from app.core.tenant import TenantContext
from app.schemas.public_chat import PublicChatRequest


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


@pytest.mark.asyncio
async def test_public_messages_disable_private_dossier_tracking():
    tenant = TenantContext(
        id=uuid.uuid4(),
        slug="prospect",
        name="Institution Exemple",
        status="active",
        whatsapp_config=None,
    )
    redis = AsyncMock()
    redis.get.return_value = '{"tenant": "prospect"}'
    contacts = SimpleNamespace(
        get_or_create_web_session=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), phone="web")
        )
    )
    conversation = SimpleNamespace(id=uuid.uuid4(), metadata_={})
    conversations = SimpleNamespace(
        get_or_create=AsyncMock(return_value=conversation),
        add_message=AsyncMock(),
        get_history=AsyncMock(return_value=[]),
        update_metadata=AsyncMock(),
    )
    run = AsyncMock(return_value={"response": "indisponible", "sources": []})
    with (
        patch(
            "app.api.v1.public_chat._resolve_public_tenant",
            AsyncMock(return_value=(tenant, SimpleNamespace(public_config={}))),
        ),
        patch("app.api.v1.public_chat._check_rate_limit", AsyncMock()),
        patch("app.api.v1.public_chat.get_redis", return_value=redis),
        patch("app.api.v1.public_chat.get_contact_service", return_value=contacts),
        patch("app.api.v1.public_chat.get_conversation_service", return_value=conversations),
        patch("app.api.v1.public_chat.run_conversation", run),
    ):
        await send_message("prospect", PublicChatRequest(message="Suivre mon dossier"), "session")
    assert run.await_args.kwargs["tracking_available"] is False
