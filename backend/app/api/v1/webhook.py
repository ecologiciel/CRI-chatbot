"""WhatsApp webhook endpoints.

GET  /api/v1/webhook/whatsapp — Meta subscription verification
POST /api/v1/webhook/whatsapp — Receive webhook events

These paths are excluded from TenantMiddleware (see middleware.py).
Tenant resolution happens inside the webhook service via phone_number_id.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.core.exceptions import WhatsAppSignatureError
from app.services.whatsapp.webhook import WhatsAppWebhookService

logger = structlog.get_logger()

router = APIRouter(prefix="/webhook", tags=["webhook"])

webhook_service = WhatsAppWebhookService()


@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    x_demo_webhook_proxy: str | None = Header(default=None),
) -> PlainTextResponse:
    """Meta webhook verification (subscription setup).

    Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.
    We verify the token and echo back the challenge string.
    """
    _require_proxy_secret(x_demo_webhook_proxy)
    try:
        challenge = webhook_service.verify_webhook(
            mode=hub_mode,
            token=hub_verify_token,
            challenge=hub_challenge,
        )
        return PlainTextResponse(content=challenge)
    except WhatsAppSignatureError as exc:
        logger.warning("whatsapp_verify_failed", error=exc.message)
        return JSONResponse(
            status_code=403,
            content={"error": "Verification failed", "message": exc.message},
        )


@router.post("/whatsapp")
async def receive_whatsapp_webhook(
    request: Request,
    x_demo_webhook_proxy: str | None = Header(default=None),
) -> JSONResponse:
    """Receive webhook events from Meta.

    IMPORTANT: Always returns 200 to prevent Meta from retrying.
    The only exception is 403 on HMAC signature failure.

    Raw body is read directly for HMAC verification — we do NOT use
    a Pydantic body parameter because that would re-serialize the JSON.
    """
    _require_proxy_secret(x_demo_webhook_proxy)
    maximum = get_settings().whatsapp_webhook_max_body_bytes
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
        body.extend(chunk)
    raw_body = bytes(body)
    signature = request.headers.get("X-Hub-Signature-256")

    try:
        await webhook_service.process_webhook(raw_body, signature)
    except WhatsAppSignatureError as exc:
        logger.warning("whatsapp_hmac_failed", error=exc.message)
        return JSONResponse(
            status_code=403,
            content={"error": "Invalid signature", "message": exc.message},
        )
    except Exception:
        # Catch ALL other errors — always return 200 to Meta.
        # Errors are logged inside process_webhook and here as a safety net.
        logger.exception("whatsapp_webhook_unhandled_error")

    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
    )


def _require_proxy_secret(provided: str | None) -> None:
    """Restrict webhook traffic to the configured relay when one is enabled."""
    configured = get_settings().webhook_proxy_shared_secret
    if configured and not hmac.compare_digest(configured, provided or ""):
        raise HTTPException(status_code=403, detail="Webhook relay authentication failed")
