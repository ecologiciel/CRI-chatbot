"""Approved Meta template selection without calling Meta or sending messages."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1.campaigns import list_approved_templates
from app.core.tenant import TenantContext
from app.services.campaign.templates import _supported_template, approved_templates


def tenant(config=None):
    return TenantContext(
        id=uuid.uuid4(), slug="test", name="Test", status="active", whatsapp_config=config
    )


def example(**overrides):
    return {
        "id": "123",
        "name": "approved_notice",
        "language": "fr",
        "status": "APPROVED",
        "components": [{"type": "BODY", "text": "Bonjour {{1}}"}],
        **overrides,
    }


@pytest.mark.asyncio
async def test_unconfigured_tenant_does_not_call_provider():
    with patch("app.services.campaign.templates.httpx.AsyncClient") as client:
        result = await approved_templates(tenant())
    assert result == {"configured": False, "items": [], "next_cursor": None}
    client.assert_not_called()


@pytest.mark.asyncio
async def test_meta_pagination_uses_fixed_host_and_filters_templates():
    response = MagicMock()
    response.json.return_value = {
        "data": [example(), example(id="2", status="PENDING")],
        "paging": {"next": "https://untrusted.example/", "cursors": {"after": "cursor-1"}},
    }
    client = AsyncMock()
    client.get.return_value = response
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.campaign.templates.httpx.AsyncClient", return_value=context):
        result = await approved_templates(
            tenant({"business_account_id": "1234", "access_token": "not-a-real-token"}), "previous"
        )
    assert [item["id"] for item in result["items"]] == ["123"]
    assert result["items"][0]["variables"] == ["1"]
    assert result["next_cursor"] == "cursor-1"
    assert client.get.call_args.args[0] == "https://graph.facebook.com/v27.0/1234/message_templates"
    assert client.get.call_args.kwargs["params"]["after"] == "previous"
    assert "not-a-real-token" not in str(result)


@pytest.mark.parametrize(
    "components",
    [
        [{"type": "BODY", "text": "Bonjour {{name}}"}],
        [{"type": "BODY", "text": "Bonjour {{2}}"}],
        [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Bonjour"}],
        [
            {"type": "HEADER", "format": "TEXT", "text": "{{1}}"},
            {"type": "BODY", "text": "Bonjour"},
        ],
        [
            {"type": "BODY", "text": "Bonjour"},
            {
                "type": "BUTTONS",
                "buttons": [{"type": "URL", "text": "Voir", "url": "https://example.com/{{1}}"}],
            },
        ],
    ],
)
def test_unsupported_components_are_not_shown(components):
    assert _supported_template(example(components=components)) is None


@pytest.mark.asyncio
async def test_api_does_not_expose_provider_error():
    request = httpx.Request("GET", "https://graph.facebook.com/")
    error = httpx.HTTPStatusError("sensitive-token", request=request, response=httpx.Response(403))
    with patch("app.api.v1.campaigns.approved_templates", new=AsyncMock(side_effect=error)):
        with pytest.raises(HTTPException) as exc:
            await list_approved_templates(tenant(), None, None)
    assert exc.value.status_code == 502
    assert "sensitive-token" not in exc.value.detail
