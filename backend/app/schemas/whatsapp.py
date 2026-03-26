"""Pydantic v2 schemas for WhatsApp Cloud API payloads.

Inbound models mirror Meta's webhook JSON structure.
Outbound models are used to build messages sent via Meta Cloud API v21.0.

All inbound models use extra="allow" to tolerate Meta adding new fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Inbound: Meta webhook → our server
# ---------------------------------------------------------------------------

class WebhookMetadata(BaseModel):
    """Metadata block inside a webhook change value."""

    display_phone_number: str
    phone_number_id: str

    model_config = ConfigDict(extra="allow")


class TextContent(BaseModel):
    """Text message content."""

    body: str

    model_config = ConfigDict(extra="allow")


class MediaContent(BaseModel):
    """Media (image/audio/document) content."""

    id: str
    mime_type: str = ""
    sha256: str | None = None
    caption: str | None = None

    model_config = ConfigDict(extra="allow")


class InteractiveReply(BaseModel):
    """Reply from an interactive button or list selection."""

    id: str
    title: str

    model_config = ConfigDict(extra="allow")


class InteractiveContent(BaseModel):
    """Interactive message reply (button_reply or list_reply)."""

    type: str
    button_reply: InteractiveReply | None = None
    list_reply: InteractiveReply | None = None

    model_config = ConfigDict(extra="allow")


class ButtonContent(BaseModel):
    """Quick reply button content."""

    payload: str
    text: str

    model_config = ConfigDict(extra="allow")


class IncomingMessage(BaseModel):
    """A single inbound WhatsApp message.

    The ``id`` field is the wamid used for deduplication.
    ``from_`` uses alias="from" because ``from`` is a Python keyword.
    """

    id: str
    from_: str = Field(..., alias="from")
    timestamp: str
    type: str

    # Content fields — only one is populated per message type
    text: TextContent | None = None
    image: MediaContent | None = None
    audio: MediaContent | None = None
    document: MediaContent | None = None
    interactive: InteractiveContent | None = None
    button: ButtonContent | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ContactInfo(BaseModel):
    """Sender contact info from webhook."""

    profile: dict
    wa_id: str

    model_config = ConfigDict(extra="allow")


class StatusInfo(BaseModel):
    """Message delivery status update."""

    id: str
    status: str  # "sent", "delivered", "read", "failed"
    timestamp: str
    recipient_id: str
    errors: list[dict] | None = None

    model_config = ConfigDict(extra="allow")


class WebhookValue(BaseModel):
    """The ``value`` block inside a webhook change."""

    messaging_product: str
    metadata: WebhookMetadata
    contacts: list[ContactInfo] | None = None
    messages: list[IncomingMessage] | None = None
    statuses: list[StatusInfo] | None = None

    model_config = ConfigDict(extra="allow")


class WebhookChange(BaseModel):
    """A single change entry in the webhook payload."""

    value: WebhookValue
    field: str

    model_config = ConfigDict(extra="allow")


class WebhookEntry(BaseModel):
    """An entry in the top-level webhook payload."""

    id: str
    changes: list[WebhookChange]

    model_config = ConfigDict(extra="allow")


class WhatsAppWebhookPayload(BaseModel):
    """Top-level webhook payload from Meta.

    Meta sends this JSON to POST /api/v1/webhook/whatsapp.
    """

    object: str = Field(..., alias="object")
    entry: list[WebhookEntry]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------------------
# Outbound: our server → Meta Cloud API
# ---------------------------------------------------------------------------

class SendTextMessage(BaseModel):
    """Payload to send a text message."""

    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: dict  # {"body": "..."}


class SendInteractiveMessage(BaseModel):
    """Payload to send an interactive message (buttons or list)."""

    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "interactive"
    interactive: dict


class SendTemplateMessage(BaseModel):
    """Payload to send a template message (for notifications outside 24h window)."""

    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "template"
    template: dict  # {"name": "...", "language": {"code": "fr"}, "components": [...]}
