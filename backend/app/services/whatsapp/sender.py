"""WhatsApp message sender via Meta Cloud API v21.0.

All methods receive a TenantContext to extract per-tenant WhatsApp
credentials (phone_number_id, access_token) from tenant.whatsapp_config.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.core.exceptions import WhatsAppSendError
from app.core.tenant import TenantContext
from app.schemas.whatsapp import (
    SendInteractiveMessage,
    SendTemplateMessage,
    SendTextMessage,
)

logger = structlog.get_logger()

BASE_URL = "https://graph.facebook.com/v21.0"
TIMEOUT = 30.0
MAX_BUTTONS = 3


class WhatsAppSenderService:
    """Sends messages to WhatsApp users via Meta Cloud API."""

    async def send_text(
        self,
        tenant: TenantContext,
        to: str,
        body: str,
    ) -> str:
        """Send a text message.

        Args:
            tenant: Current tenant context.
            to: Recipient phone number (E.164).
            body: Message text.

        Returns:
            The wamid of the sent message.
        """
        payload = SendTextMessage(to=to, text={"body": body})
        response = await self._send_request(tenant, payload.model_dump())
        return self._extract_wamid(response)

    async def send_buttons(
        self,
        tenant: TenantContext,
        to: str,
        body_text: str,
        buttons: list[dict[str, str]],
    ) -> str:
        """Send an interactive message with reply buttons (max 3).

        Args:
            tenant: Current tenant context.
            to: Recipient phone number.
            body_text: Message body text.
            buttons: List of dicts with ``id`` and ``title`` keys.

        Returns:
            The wamid of the sent message.

        Raises:
            ValueError: If more than 3 buttons are provided.
        """
        if len(buttons) > MAX_BUTTONS:
            raise ValueError(f"WhatsApp allows at most {MAX_BUTTONS} buttons, got {len(buttons)}")

        interactive = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
                    for btn in buttons
                ]
            },
        }
        payload = SendInteractiveMessage(to=to, interactive=interactive)
        response = await self._send_request(tenant, payload.model_dump())
        return self._extract_wamid(response)

    async def send_list(
        self,
        tenant: TenantContext,
        to: str,
        body_text: str,
        button_text: str,
        sections: list[dict[str, Any]],
    ) -> str:
        """Send an interactive list message.

        Args:
            tenant: Current tenant context.
            to: Recipient phone number.
            body_text: Message body text.
            button_text: Text on the list trigger button.
            sections: List sections, each with ``title`` and ``rows``.

        Returns:
            The wamid of the sent message.
        """
        interactive = {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": button_text, "sections": sections},
        }
        payload = SendInteractiveMessage(to=to, interactive=interactive)
        response = await self._send_request(tenant, payload.model_dump())
        return self._extract_wamid(response)

    async def send_template(
        self,
        tenant: TenantContext,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]] | None = None,
    ) -> str:
        """Send a template message (for notifications outside the 24h window).

        Args:
            tenant: Current tenant context.
            to: Recipient phone number.
            template_name: Pre-approved Meta template name.
            language_code: ISO language code (e.g. ``fr``, ``ar``).
            components: Optional template components.

        Returns:
            The wamid of the sent message.
        """
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components

        payload = SendTemplateMessage(to=to, template=template)
        response = await self._send_request(tenant, payload.model_dump())
        return self._extract_wamid(response)

    async def mark_as_read(
        self,
        tenant: TenantContext,
        message_id: str,
    ) -> None:
        """Mark a received message as read (sends blue ticks).

        Args:
            tenant: Current tenant context.
            message_id: The wamid of the message to mark as read.
        """
        phone_number_id, access_token = self._get_credentials(tenant)
        url = f"{BASE_URL}/{phone_number_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()

        logger.debug(
            "whatsapp_message_marked_read",
            tenant_slug=tenant.slug,
            message_id=message_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_request(
        self,
        tenant: TenantContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST a message payload to Meta Cloud API.

        Args:
            tenant: Current tenant context.
            payload: Serialized message payload.

        Returns:
            Meta API JSON response.

        Raises:
            WhatsAppSendError: On any HTTP or Meta API error.
        """
        phone_number_id, access_token = self._get_credentials(tenant)
        url = f"{BASE_URL}/{phone_number_id}/messages"

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.json() if exc.response else {}
            meta_error = error_body.get("error", {})
            raise WhatsAppSendError(
                f"Meta API error {exc.response.status_code}: {meta_error.get('message', 'Unknown')}",
                details={
                    "status_code": exc.response.status_code,
                    "meta_error_code": meta_error.get("code"),
                    "meta_error_message": meta_error.get("message"),
                    "tenant_slug": tenant.slug,
                },
            ) from exc
        except httpx.TimeoutException as exc:
            raise WhatsAppSendError(
                "Meta API request timed out",
                details={"tenant_slug": tenant.slug, "timeout": TIMEOUT},
            ) from exc

        logger.info(
            "whatsapp_message_sent",
            tenant_slug=tenant.slug,
            message_type=payload.get("type"),
            to=self._mask_phone(payload.get("to", "")),
        )
        return data

    @staticmethod
    def _get_credentials(tenant: TenantContext) -> tuple[str, str]:
        """Extract WhatsApp credentials from tenant config.

        Returns:
            Tuple of (phone_number_id, access_token).

        Raises:
            WhatsAppSendError: If WhatsApp is not configured for this tenant.
        """
        config = tenant.whatsapp_config
        if not config:
            raise WhatsAppSendError(
                "WhatsApp not configured for this tenant",
                details={"tenant_slug": tenant.slug},
            )

        phone_number_id = config.get("phone_number_id", "")
        access_token = config.get("access_token", "")

        if not phone_number_id or not access_token:
            raise WhatsAppSendError(
                "Missing phone_number_id or access_token in WhatsApp config",
                details={"tenant_slug": tenant.slug},
            )

        return phone_number_id, access_token

    @staticmethod
    def _extract_wamid(response: dict[str, Any]) -> str:
        """Extract the wamid from Meta's send response."""
        try:
            return response["messages"][0]["id"]
        except (KeyError, IndexError) as exc:
            raise WhatsAppSendError(
                "Unexpected Meta API response format",
                details={"response": response},
            ) from exc

    @staticmethod
    def _mask_phone(phone: str) -> str:
        """Mask phone number for logging (show last 4 digits)."""
        if len(phone) > 4:
            return f"***{phone[-4:]}"
        return "***"
