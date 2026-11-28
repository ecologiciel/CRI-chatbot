"""Tenant-bound Meta webhook authentication, not yet exposed as a route.

Authentication and whole-payload validation must precede any message or
status side effect. A future durable intake must recheck channel ownership
under its transaction lock before persisting each event.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from pydantic import ValidationError

from app.core.exceptions import TenantInactiveError, WhatsAppSignatureError
from app.core.tenant import TenantContext, TenantResolver
from app.schemas.whatsapp import WhatsAppWebhookPayload

_SIGNATURE = re.compile(r"sha256=[0-9a-f]{64}\Z")
_MAX_SECRET_BYTES = 4096


class TenantWebhookPayloadError(ValueError):
    """The authenticated payload cannot be safely assigned to this channel."""


def _secret(config: dict | None, name: str) -> bytes:
    value = config.get(name) if isinstance(config, dict) else None
    if not isinstance(value, str) or not value:
        raise WhatsAppSignatureError("Webhook authentication unavailable")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise WhatsAppSignatureError("Webhook authentication unavailable") from None
    if len(encoded) > _MAX_SECRET_BYTES:
        raise WhatsAppSignatureError("Webhook authentication unavailable")
    return encoded


async def require_current_signing_secret(tenant: TenantContext, current, session) -> None:
    """Reject rotation between authentication and the locked database write."""
    expected = _secret(tenant.whatsapp_config, "app_secret")
    resolved = await TenantResolver._build_context(current, session=session)
    actual = _secret(resolved.whatsapp_config, "app_secret")
    if not hmac.compare_digest(expected, actual):
        raise TenantInactiveError("WhatsApp channel credentials have changed")


def verify_tenant_challenge(tenant: TenantContext, mode: str, token: str, challenge: str) -> str:
    """Return the challenge only after this institution's token is verified."""
    _secret(tenant.whatsapp_config, "app_secret")
    expected = _secret(tenant.whatsapp_config, "verify_token")
    try:
        supplied = token.encode("utf-8") if isinstance(token, str) else b""
    except UnicodeEncodeError:
        supplied = b""
    if mode != "subscribe" or not supplied or not hmac.compare_digest(expected, supplied):
        raise WhatsAppSignatureError("Webhook verification failed")
    return challenge


def authenticate_tenant_payload(
    tenant: TenantContext, raw_body: bytes, signature: str | None,
) -> WhatsAppWebhookPayload:
    """Verify this tenant's signature, then bind every event to its phone ID."""
    secret = _secret(tenant.whatsapp_config, "app_secret")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        raise WhatsAppSignatureError("Webhook signature invalid")
    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WhatsAppSignatureError("Webhook signature invalid")
    try:
        payload = WhatsAppWebhookPayload.model_validate_json(raw_body)
    except ValidationError:
        raise TenantWebhookPayloadError("Invalid webhook payload") from None
    config = tenant.whatsapp_config or {}
    phone = config.get("phone_number_id")
    changes = [change for entry in payload.entry for change in entry.changes]
    if (
        payload.object != "whatsapp_business_account"
        or not isinstance(phone, str) or not phone.isascii() or not phone.isdecimal()
        or not changes
        or any(change.field != "messages" or change.value.metadata.phone_number_id != phone
               or not (change.value.messages or change.value.statuses) for change in changes)
    ):
        raise TenantWebhookPayloadError("Webhook event does not match the configured channel")
    return payload
