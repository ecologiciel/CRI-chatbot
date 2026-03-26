"""Tests for WhatsApp sender service.

Covers: send text, buttons (max 3), list, template, Meta API error handling.

NOTE: httpx.Response.json() and .raise_for_status() are sync methods,
so the mock response uses MagicMock (not AsyncMock).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.exceptions import WhatsAppSendError
from app.core.tenant import TenantContext
from app.services.whatsapp.sender import WhatsAppSenderService


# --- Fixtures ---

TEST_TENANT_ID = uuid.uuid4()


def _make_tenant_context(**overrides) -> TenantContext:
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat-Salé-Kénitra",
        "status": "active",
        "whatsapp_config": {
            "phone_number_id": "111222333",
            "access_token": "test_access_token",
            "verify_token": "test_verify_token",
        },
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


def _make_mock_response(wamid: str = "wamid.sent_123") -> MagicMock:
    """Create a mock httpx.Response with sync .json() and .raise_for_status()."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "+212600000001", "wa_id": "212600000001"}],
        "messages": [{"id": wamid}],
    }
    response.raise_for_status = MagicMock()  # sync, no-op on success
    return response


def _make_mock_client(response: MagicMock) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns the given response on POST."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


# --- Tests ---


class TestSendText:
    @pytest.mark.asyncio
    async def test_send_text_success(self):
        """send_text() should POST correct payload and return wamid."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()
        expected_wamid = "wamid.text_123"

        mock_response = _make_mock_response(expected_wamid)
        mock_client = _make_mock_client(mock_response)

        with patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client):
            wamid = await sender.send_text(tenant, "+212600000001", "Bonjour")

        assert wamid == expected_wamid

        # Verify the POST payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "+212600000001"
        assert payload["type"] == "text"
        assert payload["text"] == {"body": "Bonjour"}


class TestSendButtons:
    @pytest.mark.asyncio
    async def test_send_buttons_success(self):
        """send_buttons() with 3 buttons should succeed."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()

        mock_response = _make_mock_response("wamid.btn_123")
        mock_client = _make_mock_client(mock_response)

        buttons = [
            {"id": "btn_1", "title": "Option 1"},
            {"id": "btn_2", "title": "Option 2"},
            {"id": "btn_3", "title": "Option 3"},
        ]

        with patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client):
            wamid = await sender.send_buttons(tenant, "+212600000001", "Choose:", buttons)

        assert wamid == "wamid.btn_123"

        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["type"] == "interactive"
        assert payload["interactive"]["type"] == "button"
        assert len(payload["interactive"]["action"]["buttons"]) == 3

    @pytest.mark.asyncio
    async def test_send_buttons_exceeds_limit(self):
        """send_buttons() with >3 buttons should raise ValueError."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()

        buttons = [
            {"id": f"btn_{i}", "title": f"Option {i}"}
            for i in range(4)
        ]

        with pytest.raises(ValueError, match="at most 3 buttons"):
            await sender.send_buttons(tenant, "+212600000001", "Choose:", buttons)


class TestSendList:
    @pytest.mark.asyncio
    async def test_send_list_success(self):
        """send_list() should format sections correctly."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()

        mock_response = _make_mock_response("wamid.list_123")
        mock_client = _make_mock_client(mock_response)

        sections = [
            {
                "title": "Procédures",
                "rows": [
                    {"id": "proc_1", "title": "Création d'entreprise", "description": "SARL, SA, SNC"},
                    {"id": "proc_2", "title": "Convention d'investissement"},
                ],
            }
        ]

        with patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client):
            wamid = await sender.send_list(
                tenant, "+212600000001", "Choisissez un service:", "Services", sections,
            )

        assert wamid == "wamid.list_123"

        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["interactive"]["type"] == "list"
        assert payload["interactive"]["action"]["button"] == "Services"
        assert len(payload["interactive"]["action"]["sections"]) == 1


class TestSendTemplate:
    @pytest.mark.asyncio
    async def test_send_template_success(self):
        """send_template() should format template payload correctly."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()

        mock_response = _make_mock_response("wamid.tpl_123")
        mock_client = _make_mock_client(mock_response)

        with patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client):
            wamid = await sender.send_template(
                tenant, "+212600000001", "welcome_message", "fr",
            )

        assert wamid == "wamid.tpl_123"

        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "welcome_message"
        assert payload["template"]["language"] == {"code": "fr"}


class TestMetaErrorHandling:
    @pytest.mark.asyncio
    async def test_meta_api_error(self):
        """HTTP error from Meta API should raise WhatsAppSendError."""
        tenant = _make_tenant_context()
        sender = WhatsAppSenderService()

        # httpx.Response uses sync .json() and .raise_for_status()
        mock_error_body = MagicMock()
        mock_error_body.status_code = 400
        mock_error_body.json.return_value = {
            "error": {
                "message": "Invalid parameter",
                "type": "OAuthException",
                "code": 100,
                "fbtrace_id": "trace123",
            }
        }

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request",
            request=httpx.Request("POST", "https://graph.facebook.com/v21.0/111222333/messages"),
            response=mock_error_body,
        )

        mock_client = _make_mock_client(mock_response)

        with (
            patch("app.services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(WhatsAppSendError, match="Meta API error"),
        ):
            await sender.send_text(tenant, "+212600000001", "Test")

    @pytest.mark.asyncio
    async def test_missing_whatsapp_config(self):
        """Tenant without WhatsApp config should raise WhatsAppSendError."""
        tenant = _make_tenant_context(whatsapp_config=None)
        sender = WhatsAppSenderService()

        with pytest.raises(WhatsAppSendError, match="not configured"):
            await sender.send_text(tenant, "+212600000001", "Test")
