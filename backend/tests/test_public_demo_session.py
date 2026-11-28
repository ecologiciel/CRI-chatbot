"""Public session identifies the institution selected for the demo."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response

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
    redis.eval.return_value = 1
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
    redis.eval.return_value = 1
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
        await send_message(
            "prospect",
            PublicChatRequest(message="Suivre mon dossier, téléphone 0522123456"),
            "session",
        )
    assert run.await_args.kwargs["tracking_available"] is False
    assert run.await_args.kwargs["channel"] == "web"
    stored_input = conversations.add_message.await_args_list[0].args[-1]
    assert "0522123456" not in stored_input
    assert "[PHONE_1]" in stored_input
    assert run.await_args.kwargs["query"] == stored_input


@pytest.mark.asyncio
async def test_new_sessions_cannot_bypass_shared_message_limit():
    tenant = TenantContext(uuid.uuid4(), "prospect", "Institution", "active", None)
    counters: dict[str, int] = {}

    async def increment(_script, _key_count, key, _ttl):
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    redis = AsyncMock()
    redis.get.return_value = '{"tenant": "prospect"}'
    redis.eval.side_effect = increment
    contacts = SimpleNamespace(
        get_or_create_web_session=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), phone="web")
        )
    )
    conversations = SimpleNamespace(
        get_or_create=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), metadata_={})),
        add_message=AsyncMock(),
        get_history=AsyncMock(return_value=[]),
        update_metadata=AsyncMock(),
    )
    run = AsyncMock(return_value={"response": "Réponse", "sources": []})
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
        patch("app.api.v1.public_chat.TENANT_MESSAGE_LIMIT", 2),
    ):
        for cookie in ("session-1", "session-2"):
            await send_message("prospect", PublicChatRequest(message="Bonjour"), cookie)
        with pytest.raises(HTTPException) as exc:
            await send_message("prospect", PublicChatRequest(message="Bonjour"), "session-3")
    assert exc.value.status_code == 429
    assert run.await_count == 2
    assert counters["prospect:rl:web:shared:message"] == 3


@pytest.mark.asyncio
async def test_session_creation_platform_limit_is_shared_across_institutions():
    tenants = {
        slug: TenantContext(uuid.uuid4(), slug, slug, "active", None)
        for slug in ("first", "second", "third")
    }
    counters: dict[str, int] = {}

    async def increment(_script, _key_count, key, _ttl):
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    async def resolve(slug):
        return tenants[slug], None

    redis = AsyncMock()
    redis.eval.side_effect = increment
    with (
        patch("app.api.v1.public_chat._resolve_public_tenant", side_effect=resolve),
        patch("app.api.v1.public_chat.get_redis", return_value=redis),
        patch("app.api.v1.public_chat.PLATFORM_SESSION_LIMIT", 2),
    ):
        await create_session("first", Response())
        await create_session("second", Response())
        with pytest.raises(HTTPException) as exc:
            await create_session("third", Response())
    assert exc.value.status_code == 429
    assert redis.setex.await_count == 2
