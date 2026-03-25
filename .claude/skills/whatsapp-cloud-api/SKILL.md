---
name: whatsapp-cloud-api
description: |
  Use this skill when writing any code related to WhatsApp integration for the CRI chatbot platform.
  Triggers: any mention of 'WhatsApp', 'webhook', 'Meta Cloud API', 'send message', 'receive message',
  'interactive message', 'template message', 'WhatsApp button', 'WhatsApp list', 'media message',
  'HMAC signature', 'phone_number_id', 'OTP WhatsApp', 'notification proactive', 'campaign',
  'publipostage', or any endpoint under /api/v1/webhook/. Also triggers when working on the
  whatsapp/ service directory. Do NOT use for general HTTP/API questions unrelated to WhatsApp.
---

# WhatsApp Cloud API Integration — CRI Chatbot Platform

## Overview

Each tenant has its own WhatsApp Business Account with a dedicated phone number.
The CRI platform uses **Meta Cloud API (v21.0+)** directly (no intermediary like 360dialog).
All WhatsApp credentials are tenant-scoped via `tenant.whatsapp_config`.

## 1. Webhook Setup & Verification

### 1.1 Webhook Verification (GET)

Meta sends a GET request to verify the webhook URL during setup:

```python
# app/api/v1/webhook.py

@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    """Meta webhook verification challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")
```

### 1.2 Webhook Reception (POST) with HMAC Validation

**CRITICAL: Always validate the HMAC-SHA256 signature before processing any webhook.**

```python
import hashlib
import hmac

@router.post("/webhook/whatsapp", status_code=200)
async def receive_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Receive and process WhatsApp webhook events."""
    # Step 1: Validate HMAC-SHA256 signature
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing signature")

    body = await request.body()
    expected_signature = hmac.new(
        settings.whatsapp_app_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature_header[7:], expected_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Step 2: Parse payload with Pydantic
    payload = WebhookPayload.model_validate_json(body)

    # Step 3: Process each entry (may contain multiple)
    for entry in payload.entry:
        for change in entry.changes:
            if change.field == "messages":
                await process_messages(change.value)
            elif change.field == "message_template_status_update":
                await process_template_status(change.value)

    # Step 4: Always return 200 (Meta retries on non-200)
    return {"status": "ok"}
```

### 1.3 Webhook Payload Schemas (Pydantic v2)

```python
# app/schemas/whatsapp.py

from pydantic import BaseModel, Field
from typing import Literal

class WebhookPayload(BaseModel):
    object: Literal["whatsapp_business_account"]
    entry: list[WebhookEntry]

class WebhookEntry(BaseModel):
    id: str
    changes: list[WebhookChange]

class WebhookChange(BaseModel):
    field: str
    value: WebhookValue

class WebhookValue(BaseModel):
    messaging_product: Literal["whatsapp"]
    metadata: WebhookMetadata
    contacts: list[WebhookContact] | None = None
    messages: list[IncomingMessage] | None = None
    statuses: list[MessageStatus] | None = None

class WebhookMetadata(BaseModel):
    display_phone_number: str
    phone_number_id: str  # Used for tenant resolution

class IncomingMessage(BaseModel):
    id: str                                    # wamid for deduplication
    from_: str = Field(alias="from")           # Sender phone E.164
    timestamp: str
    type: Literal["text", "image", "audio", "document", "interactive", "button", "reaction", "location", "contacts"]
    text: TextContent | None = None
    image: MediaContent | None = None
    audio: MediaContent | None = None
    document: MediaContent | None = None
    interactive: InteractiveResponse | None = None
    button: ButtonResponse | None = None
    context: MessageContext | None = None       # Reply context

class TextContent(BaseModel):
    body: str

class MediaContent(BaseModel):
    id: str               # Media ID for download
    mime_type: str
    sha256: str | None = None
    caption: str | None = None

class InteractiveResponse(BaseModel):
    type: Literal["button_reply", "list_reply"]
    button_reply: ButtonReply | None = None
    list_reply: ListReply | None = None

class ButtonReply(BaseModel):
    id: str
    title: str

class ListReply(BaseModel):
    id: str
    title: str
    description: str | None = None

class MessageStatus(BaseModel):
    id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: str
    recipient_id: str
    errors: list[dict] | None = None
```

## 2. Sending Messages

### 2.1 Base Send Function (Always Tenant-Scoped)

```python
# app/services/whatsapp/sender.py

import httpx
import structlog
from app.core.tenant import TenantContext

logger = structlog.get_logger()

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

async def send_whatsapp_message(
    to: str,
    payload: dict,
    tenant: TenantContext,
) -> dict:
    """Send a WhatsApp message using the tenant's credentials."""
    wa = tenant.whatsapp_config
    url = f"{GRAPH_API_BASE}/{wa['phone_number_id']}/messages"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {wa['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                **payload,
            },
        )

    if response.status_code != 200:
        logger.error(
            "whatsapp_send_failed",
            tenant=tenant.slug,
            to=to[:6] + "****",  # Mask phone in logs
            status=response.status_code,
            error=response.json(),
        )
        raise WhatsAppSendError(response.json())

    result = response.json()
    logger.info(
        "whatsapp_message_sent",
        tenant=tenant.slug,
        wamid=result["messages"][0]["id"],
        type=payload.get("type", "unknown"),
    )
    return result
```

### 2.2 Text Messages

```python
async def send_text(to: str, text: str, tenant: TenantContext) -> dict:
    """Send a simple text message."""
    return await send_whatsapp_message(
        to=to,
        payload={"type": "text", "text": {"body": text, "preview_url": False}},
        tenant=tenant,
    )
```

### 2.3 Interactive Buttons (max 3 buttons)

Used for: feedback (👍/👎/❓), binary choices, quick actions.

```python
async def send_buttons(
    to: str,
    body: str,
    buttons: list[dict[str, str]],  # [{"id": "btn_yes", "title": "Oui"}]
    tenant: TenantContext,
    header: str | None = None,
    footer: str | None = None,
) -> dict:
    """Send an interactive button message (max 3 buttons, title max 20 chars)."""
    assert len(buttons) <= 3, "WhatsApp allows max 3 buttons"
    assert all(len(b["title"]) <= 20 for b in buttons), "Button title max 20 chars"

    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    return await send_whatsapp_message(
        to=to,
        payload={"type": "interactive", "interactive": interactive},
        tenant=tenant,
    )
```

### 2.4 Interactive Lists (max 10 items per section, 10 sections)

Used for: incentives tree (sectors, legal forms), FAQ categories.

```python
async def send_list(
    to: str,
    body: str,
    button_text: str,  # max 20 chars, the "open list" button
    sections: list[dict],
    tenant: TenantContext,
    header: str | None = None,
    footer: str | None = None,
) -> dict:
    """Send an interactive list message.

    sections format:
    [
        {
            "title": "Section Title",
            "rows": [
                {"id": "row_1", "title": "Row Title", "description": "Optional desc"},
            ]
        }
    ]
    """
    assert len(button_text) <= 20, "Button text max 20 chars"
    assert all(len(r["title"]) <= 24 for s in sections for r in s["rows"]), "Row title max 24 chars"

    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button_text, "sections": sections},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    return await send_whatsapp_message(
        to=to,
        payload={"type": "interactive", "interactive": interactive},
        tenant=tenant,
    )
```

### 2.5 Template Messages (for proactive notifications)

**Required for**: messages sent outside the 24h session window (notifications, campaigns).
Templates must be pre-approved by Meta.

```python
async def send_template(
    to: str,
    template_name: str,
    language_code: str,  # "fr", "ar", "en"
    components: list[dict] | None = None,
    tenant: TenantContext,
) -> dict:
    """Send a pre-approved template message.

    components format (for variable substitution):
    [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "M. Ahmed"},
                {"type": "text", "text": "RC-2024-001"},
            ]
        }
    ]
    """
    template_payload = {
        "name": template_name,
        "language": {"code": language_code},
    }
    if components:
        template_payload["components"] = components

    return await send_whatsapp_message(
        to=to,
        payload={"type": "template", "template": template_payload},
        tenant=tenant,
    )
```

## 3. Media Handling (Multimodal Support)

### 3.1 Download Media from WhatsApp

```python
async def download_media(
    media_id: str,
    tenant: TenantContext,
) -> tuple[bytes, str]:
    """Download media from WhatsApp and return (content, mime_type).

    Two-step process: get URL, then download content.
    """
    wa = tenant.whatsapp_config
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get media URL
        url_response = await client.get(
            f"{GRAPH_API_BASE}/{media_id}",
            headers={"Authorization": f"Bearer {wa['access_token']}"},
        )
        media_url = url_response.json()["url"]
        mime_type = url_response.json().get("mime_type", "application/octet-stream")

        # Step 2: Download actual content
        content_response = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {wa['access_token']}"},
        )
        return content_response.content, mime_type
```

### 3.2 Store Media in Tenant's MinIO Bucket

```python
async def store_media(
    media_content: bytes,
    mime_type: str,
    tenant: TenantContext,
) -> str:
    """Store downloaded media in tenant's MinIO bucket."""
    ext = mime_type.split("/")[-1]
    object_name = f"media/{uuid4()}.{ext}"
    await minio_client.put_object(
        bucket_name=tenant.minio_bucket,  # "cri-{slug}"
        object_name=object_name,
        data=io.BytesIO(media_content),
        length=len(media_content),
        content_type=mime_type,
    )
    return object_name
```

## 4. Message Deduplication

WhatsApp may send the same webhook multiple times. Always deduplicate:

```python
async def is_duplicate_message(
    wamid: str,
    tenant: TenantContext,
) -> bool:
    """Check if message was already processed. Uses Redis with 24h TTL."""
    key = f"{tenant.redis_prefix}:msg_dedup:{wamid}"
    result = await redis.set(key, "1", ex=86400, nx=True)  # SET NX = set if not exists
    return result is None  # None means key already existed = duplicate
```

## 5. Rate Limiting

```python
# Per-user rate limit: 10 messages/minute
async def check_user_rate_limit(phone: str, tenant: TenantContext) -> bool:
    key = f"{tenant.redis_prefix}:rl:user:{phone}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= 10

# Per-tenant webhook rate limit: 50 requests/minute
async def check_webhook_rate_limit(tenant: TenantContext) -> bool:
    key = f"{tenant.redis_prefix}:rl:webhook"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= 50
```

## 6. WhatsApp Message Quota Tracking

Each tenant has 100,000 messages/year. Track usage:

```python
async def increment_message_quota(tenant: TenantContext) -> int:
    """Increment and return current message count for the tenant."""
    key = f"{tenant.redis_prefix}:quota:messages:{datetime.now().year}"
    count = await redis.incr(key)

    # Alert at 80% and 95% thresholds
    if count in (80_000, 95_000):
        logger.warning(
            "whatsapp_quota_threshold",
            tenant=tenant.slug,
            count=count,
            threshold_pct=count / 1000,
        )
    return count
```

## 7. Conversation Session Window

WhatsApp has a 24-hour session window for free-form messages.
Outside the window, only template messages are allowed.

```python
async def get_session_status(
    phone: str,
    tenant: TenantContext,
) -> Literal["active", "expired"]:
    """Check if the 24h session window is still open."""
    key = f"{tenant.redis_prefix}:wa_session:{phone}"
    exists = await redis.exists(key)
    return "active" if exists else "expired"

async def open_session_window(phone: str, tenant: TenantContext) -> None:
    """Mark session as active when user sends a message (24h TTL)."""
    key = f"{tenant.redis_prefix}:wa_session:{phone}"
    await redis.setex(key, 86400, "1")  # 24 hours
```

## 8. CRI-Specific Templates

Common templates for CRI operations (must be pre-approved by Meta):

| Template Name | Use Case | Variables |
|---|---|---|
| `dossier_status_update` | Dossier status change notification | `{1}` name, `{2}` dossier_number, `{3}` new_status |
| `document_request` | Request additional documents | `{1}` name, `{2}` dossier_number, `{3}` document_list |
| `decision_notification` | Final decision notification | `{1}` name, `{2}` dossier_number, `{3}` decision |
| `otp_verification` | OTP code for dossier tracking | `{1}` otp_code |
| `welcome_message` | First contact greeting | `{1}` cri_name |

## 9. Character Limits Reference

| Element | Max Length |
|---|---|
| Text message body | 4,096 chars |
| Interactive button title | 20 chars |
| Interactive list button text | 20 chars |
| Interactive list row title | 24 chars |
| Interactive list row description | 72 chars |
| Interactive body text | 1,024 chars |
| Interactive header text | 60 chars |
| Interactive footer text | 60 chars |
| Max buttons per message | 3 |
| Max list sections | 10 |
| Max rows per section | 10 |
| Template variable | 1,024 chars |

## 10. Error Handling

```python
class WhatsAppError(CRIBaseException):
    """Base WhatsApp error."""

class WhatsAppSendError(WhatsAppError):
    """Failed to send message via WhatsApp API."""

class WhatsAppRateLimitError(WhatsAppError):
    """WhatsApp API rate limit exceeded."""

class WhatsAppMediaError(WhatsAppError):
    """Failed to download/process WhatsApp media."""

class WhatsAppSignatureError(WhatsAppError):
    """Invalid HMAC signature on webhook."""
```

## 11. Testing WhatsApp Integration

```python
@pytest.mark.asyncio
async def test_webhook_hmac_validation():
    """Reject webhooks with invalid HMAC signature."""
    response = await client.post(
        "/api/v1/webhook/whatsapp",
        content=b'{"object": "whatsapp_business_account"}',
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_message_deduplication():
    """Same wamid should be processed only once."""
    assert not await is_duplicate_message("wamid_123", tenant_rabat)  # First time
    assert await is_duplicate_message("wamid_123", tenant_rabat)      # Duplicate!

@pytest.mark.asyncio
async def test_tenant_isolation_whatsapp():
    """Each tenant uses its own WhatsApp credentials."""
    msg1 = build_send_payload(tenant_rabat)
    msg2 = build_send_payload(tenant_tanger)
    assert msg1["phone_number_id"] != msg2["phone_number_id"]
    assert msg1["access_token"] != msg2["access_token"]
```
