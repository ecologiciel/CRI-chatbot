"""Unit tests for WhatsAppSenderService — send_text, buttons, list, template."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.exceptions import WhatsAppSendError
from app.services.whatsapp.sender import WhatsAppSenderService

_HTTPX_PATCH = "app.services.whatsapp.sender.httpx"


def _make_httpx_mock(response_json=None, status_error=False):
    """Create a mock httpx module with AsyncClient context manager."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = response_json or {
        "messages": [{"id": "wamid.test123"}],
    }
    response.raise_for_status = MagicMock()

    if status_error:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": {"code": 500, "message": "Internal Error"},
        }
        error = httpx.HTTPStatusError(
            "500 error", request=MagicMock(), response=mock_response,
        )
        response.raise_for_status = MagicMock(side_effect=error)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=response)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
    mock_httpx.HTTPStatusError = httpx.HTTPStatusError
    mock_httpx.TimeoutException = httpx.TimeoutException
    return mock_httpx, mock_client


class TestSendText:
    """WhatsAppSenderService.send_text()."""

    @pytest.mark.asyncio
    async def test_send_text_returns_wamid(self, tenant_context):
        """send_text returns the wamid from Meta response."""
        mock_httpx, client = _make_httpx_mock()
        service = WhatsAppSenderService()

        with patch(_HTTPX_PATCH, mock_httpx):
            wamid = await service.send_text(
                tenant_context, "+212600000001", "Bonjour",
            )

        assert wamid == "wamid.test123"
        client.post.assert_called_once()


class TestSendButtons:
    """WhatsAppSenderService.send_buttons() max enforcement."""

    @pytest.mark.asyncio
    async def test_buttons_max_3_enforcement(self, tenant_context):
        """4 buttons raises ValueError."""
        service = WhatsAppSenderService()
        buttons = [
            {"id": f"btn-{i}", "title": f"Button {i}"} for i in range(4)
        ]

        with pytest.raises(ValueError, match="at most 3"):
            await service.send_buttons(
                tenant_context, "+212600000001", "Choose", buttons,
            )


class TestSendList:
    """WhatsAppSenderService.send_list() formats sections."""

    @pytest.mark.asyncio
    async def test_send_list_success(self, tenant_context):
        """send_list with sections returns wamid."""
        mock_httpx, _ = _make_httpx_mock()
        service = WhatsAppSenderService()
        sections = [{
            "title": "Category",
            "rows": [{"id": "r1", "title": "Row 1"}],
        }]

        with patch(_HTTPX_PATCH, mock_httpx):
            wamid = await service.send_list(
                tenant_context, "+212600000001",
                "Choisissez:", "Options", sections,
            )

        assert wamid == "wamid.test123"


class TestMetaAPIError:
    """Meta API errors wrapped in WhatsAppSendError."""

    @pytest.mark.asyncio
    async def test_http_error_raises(self, tenant_context):
        """HTTP 500 from Meta is wrapped in WhatsAppSendError."""
        mock_httpx, _ = _make_httpx_mock(status_error=True)
        service = WhatsAppSenderService()

        with patch(_HTTPX_PATCH, mock_httpx):
            with pytest.raises(WhatsAppSendError, match="Meta API error"):
                await service.send_text(
                    tenant_context, "+212600000001", "Test",
                )


class TestMissingConfig:
    """Missing WhatsApp config raises WhatsAppSendError."""

    @pytest.mark.asyncio
    async def test_no_whatsapp_config_raises(self, tenant_no_whatsapp):
        """tenant.whatsapp_config=None raises WhatsAppSendError."""
        service = WhatsAppSenderService()

        with pytest.raises(WhatsAppSendError, match="not configured"):
            await service.send_text(
                tenant_no_whatsapp, "+212600000001", "Test",
            )
