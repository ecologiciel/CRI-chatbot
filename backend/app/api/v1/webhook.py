"""WhatsApp webhook endpoints.

GET  /api/v1/webhook/whatsapp — Meta subscription verification
POST /api/v1/webhook/whatsapp — Receive webhook events

These paths are excluded from TenantMiddleware (see middleware.py).
Tenant resolution happens inside the webhook service via phone_number_id.
"""

from __future__ import annotations

import hmac
import re

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.core.exceptions import TenantInactiveError, TenantNotFoundError, WhatsAppSignatureError
from app.core.redis import get_redis
from app.core.tenant import TenantResolver
from app.services.whatsapp.inbox_intake import persist_tenant_authenticated_webhook
from app.services.whatsapp.tenant_webhook_auth import (
    TenantWebhookPayloadError,
    verify_tenant_challenge,
)
from app.services.whatsapp.webhook import WhatsAppWebhookService
from app.services.whatsapp.worker_presence import HEARTBEAT_KEY

logger = structlog.get_logger()

router = APIRouter(prefix="/webhook", tags=["webhook"])

webhook_service = WhatsAppWebhookService()


async def _tenant_webhook_ready() -> None:
    """Heartbeat indicates a recently reachable worker, not provider delivery."""
    settings = get_settings()
    if settings.whatsapp_tenant_webhook_enabled is not True:
        raise HTTPException(status_code=404, detail="Not found")
    if settings.whatsapp_durable_inbox_enabled is not True:
        raise HTTPException(status_code=503, detail="Webhook intake unavailable")
    try:
        available = bool(await get_redis().exists(HEARTBEAT_KEY))
    except Exception:
        available = False
    if not available:
        raise HTTPException(status_code=503, detail="Webhook intake unavailable")


async def _tenant_for_webhook(slug: str):
    if not re.fullmatch(r"[a-z][a-z0-9]{1,49}", slug):
        raise HTTPException(status_code=403, detail="Webhook authentication failed")
    try:
        return await TenantResolver.from_slug(slug)
    except (TenantNotFoundError, TenantInactiveError):
        raise HTTPException(status_code=403, detail="Webhook authentication failed") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Webhook intake unavailable") from None


@router.get("/whatsapp/tenant/{slug}")
async def verify_tenant_whatsapp_webhook(
    slug: str, request: Request, x_demo_webhook_proxy: str | None = Header(default=None),
) -> PlainTextResponse:
    """Verify one institution's token without reflecting failed parameters."""
    _require_proxy_secret(x_demo_webhook_proxy)
    await _tenant_webhook_ready()
    tenant = await _tenant_for_webhook(slug)
    params = request.query_params
    if any(len(params.getlist(key)) != 1 for key in ("hub.mode", "hub.verify_token", "hub.challenge")):
        raise HTTPException(status_code=403, detail="Webhook authentication failed")
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    if len(mode) > 32 or len(token) > 4096 or not challenge or len(challenge) > 1024:
        raise HTTPException(status_code=403, detail="Webhook authentication failed")
    try:
        return PlainTextResponse(verify_tenant_challenge(tenant, mode, token, challenge))
    except WhatsAppSignatureError:
        raise HTTPException(status_code=403, detail="Webhook authentication failed") from None


@router.post("/whatsapp/tenant/{slug}")
async def receive_tenant_whatsapp_webhook(
    slug: str, request: Request, x_demo_webhook_proxy: str | None = Header(default=None),
) -> JSONResponse:
    """Acknowledge only after authenticated tenant events are committed."""
    _require_proxy_secret(x_demo_webhook_proxy)
    await _tenant_webhook_ready()
    tenant = await _tenant_for_webhook(slug)
    body = bytearray()
    maximum = get_settings().whatsapp_webhook_max_body_bytes
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
        body.extend(chunk)
    try:
        await persist_tenant_authenticated_webhook(
            tenant, bytes(body), request.headers.get("X-Hub-Signature-256")
        )
    except WhatsAppSignatureError:
        raise HTTPException(status_code=403, detail="Webhook authentication failed") from None
    except TenantWebhookPayloadError:
        raise HTTPException(status_code=400, detail="Unsupported webhook event") from None
    except Exception as exc:
        logger.error("tenant_whatsapp_intake_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Webhook intake unavailable") from None
    return JSONResponse(status_code=200, content={"status": "ok"})


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
    if get_settings().whatsapp_tenant_webhook_enabled is True:
        raise HTTPException(status_code=404, detail="Not found")
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

    Unexpected intake failures return 503. In legacy mode this does not
    guarantee safe replay: some work may already have occurred before failure.
    Durable intake acknowledges only committed events.

    Raw body is read directly for HMAC verification — we do NOT use
    a Pydantic body parameter because that would re-serialize the JSON.
    """
    if get_settings().whatsapp_tenant_webhook_enabled is True:
        raise HTTPException(status_code=404, detail="Not found")
    _require_proxy_secret(x_demo_webhook_proxy)
    maximum = get_settings().whatsapp_webhook_max_body_bytes
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
        body.extend(chunk)
    raw_body = bytes(body)
    signature = request.headers.get("X-Hub-Signature-256")

    durable = get_settings().whatsapp_durable_inbox_enabled is True
    try:
        if durable:
            from app.services.whatsapp.inbox_intake import persist_authenticated_webhook

            await persist_authenticated_webhook(raw_body, signature)
        else:
            await webhook_service.process_webhook(raw_body, signature)
    except WhatsAppSignatureError as exc:
        logger.warning("whatsapp_hmac_failed", error=exc.message)
        return JSONResponse(
            status_code=403,
            content={"error": "Invalid signature", "message": exc.message},
        )
    except Exception as exc:
        logger.error(
            "whatsapp_intake_failed", durable=durable, error_type=type(exc).__name__
        )
        return JSONResponse(status_code=503, content={"error": "Webhook intake unavailable"})

    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
    )


def _require_proxy_secret(provided: str | None) -> None:
    """Restrict webhook traffic to the configured relay when one is enabled."""
    configured = get_settings().webhook_proxy_shared_secret
    if configured and not hmac.compare_digest(configured.encode("utf-8"), (provided or "").encode("utf-8")):
        raise HTTPException(status_code=403, detail="Webhook relay authentication failed")
