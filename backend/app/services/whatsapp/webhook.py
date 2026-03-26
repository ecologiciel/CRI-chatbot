"""WhatsApp webhook processing service.

Handles incoming webhook events from Meta:
- HMAC-SHA256 signature validation (global app_secret)
- Tenant resolution via phone_number_id
- Message deduplication via Redis (wamid, 24h TTL)
- Rate limiting per tenant (50 req/min)
"""

from __future__ import annotations

import hashlib
import hmac

import structlog
from pydantic import ValidationError as PydanticValidationError

from app.core.config import get_settings
from app.core.exceptions import (
    RateLimitExceededError,
    WhatsAppSignatureError,
)
from app.core.redis import get_redis
from app.core.tenant import TenantContext, TenantResolver
from app.schemas.whatsapp import IncomingMessage, StatusInfo, WhatsAppWebhookPayload

logger = structlog.get_logger()

# Rate limit: 50 requests per 60-second window per tenant
RATE_LIMIT_MAX = 50
RATE_LIMIT_WINDOW = 60  # seconds

# Deduplication TTL: 24 hours
DEDUP_TTL = 86400


class WhatsAppWebhookService:
    """Processes incoming WhatsApp webhook events."""

    @staticmethod
    def verify_webhook(mode: str, token: str, challenge: str) -> str:
        """Handle GET webhook verification from Meta.

        Args:
            mode: Must be ``subscribe``.
            token: Verification token sent by Meta.
            challenge: Challenge string to echo back.

        Returns:
            The challenge string if verification succeeds.

        Raises:
            WhatsAppSignatureError: If mode or token is invalid.
        """
        settings = get_settings()

        if mode != "subscribe":
            raise WhatsAppSignatureError(
                f"Invalid hub.mode: {mode}",
                details={"mode": mode},
            )

        if not hmac.compare_digest(token, settings.whatsapp_verify_token):
            raise WhatsAppSignatureError(
                "Invalid verify token",
                details={"mode": mode},
            )

        logger.info("whatsapp_webhook_verified")
        return challenge

    @staticmethod
    async def process_webhook(raw_body: bytes, signature: str | None) -> None:
        """Handle POST webhook event from Meta.

        Steps:
            1. Validate HMAC-SHA256 signature (global app_secret)
            2. Parse payload into Pydantic model
            3. Resolve tenant from phone_number_id
            4. Check rate limit
            5. Process messages (dedup) and statuses

        Args:
            raw_body: Raw request body bytes (for HMAC).
            signature: Value of X-Hub-Signature-256 header.

        Raises:
            WhatsAppSignatureError: On invalid/missing HMAC signature.
        """
        # 1. Validate HMAC — must happen before any processing
        WhatsAppWebhookService._validate_hmac_signature(raw_body, signature)

        # 2. Parse payload
        try:
            payload = WhatsAppWebhookPayload.model_validate_json(raw_body)
        except PydanticValidationError as exc:
            logger.error("whatsapp_webhook_parse_error", error=str(exc))
            return

        # 3. Process each entry/change
        for entry in payload.entry:
            for change in entry.changes:
                if change.field != "messages":
                    continue

                value = change.value
                phone_number_id = value.metadata.phone_number_id

                # 4. Resolve tenant
                tenant = await TenantResolver.from_phone_number_id(phone_number_id)

                # 5. Check rate limit
                await WhatsAppWebhookService._check_rate_limit(tenant.slug)

                # 6. Process messages
                if value.messages:
                    for msg in value.messages:
                        await WhatsAppWebhookService._process_message(
                            tenant, msg, value.contacts,
                        )

                # 7. Process statuses
                if value.statuses:
                    for status in value.statuses:
                        WhatsAppWebhookService._process_status(tenant, status)

    @staticmethod
    def _validate_hmac_signature(
        raw_body: bytes, signature: str | None,
    ) -> None:
        """Verify HMAC-SHA256 signature using the global app_secret.

        Args:
            raw_body: Raw request body bytes.
            signature: Header value, format ``sha256=XXXXX``.

        Raises:
            WhatsAppSignatureError: If signature is missing or invalid.
        """
        if not signature:
            raise WhatsAppSignatureError(
                "Missing X-Hub-Signature-256 header",
            )

        settings = get_settings()
        expected = hmac.new(
            settings.whatsapp_app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(f"sha256={expected}", signature):
            raise WhatsAppSignatureError(
                "Invalid HMAC-SHA256 signature",
            )

    @staticmethod
    async def _process_message(
        tenant: TenantContext,
        msg: IncomingMessage,
        contacts: list | None,
    ) -> None:
        """Process a single inbound message with deduplication.

        Args:
            tenant: Resolved tenant context.
            msg: Parsed incoming message.
            contacts: Contact info from the webhook payload.
        """
        wamid = msg.id

        # Dedup check — SET NX returns True if key was set (new message)
        is_new = await WhatsAppWebhookService._mark_if_new(tenant.slug, wamid)
        if not is_new:
            logger.debug(
                "whatsapp_message_duplicate",
                tenant_slug=tenant.slug,
                wamid=wamid,
            )
            return

        # Extract sender info
        sender_phone = msg.from_
        sender_name = None
        if contacts:
            for contact in contacts:
                if contact.wa_id == sender_phone:
                    sender_name = contact.profile.get("name")
                    break

        # Extract message content
        content = None
        if msg.type == "text" and msg.text:
            content = msg.text.body
        elif msg.type == "interactive" and msg.interactive:
            reply = msg.interactive.button_reply or msg.interactive.list_reply
            if reply:
                content = reply.title
        elif msg.type == "button" and msg.button:
            content = msg.button.text

        logger.info(
            "whatsapp_message_received",
            tenant_slug=tenant.slug,
            wamid=wamid,
            sender_phone=f"***{sender_phone[-4:]}" if len(sender_phone) > 4 else "***",
            sender_name=sender_name,
            message_type=msg.type,
            has_content=content is not None,
        )

        # TODO: Create/update contact via ContactService
        # TODO: Create/get conversation
        # TODO: Persist message to DB
        # TODO: Dispatch to LangGraph orchestrator (Wave 8 — ORCH.5)

    @staticmethod
    def _process_status(tenant: TenantContext, status: StatusInfo) -> None:
        """Process a message delivery status update.

        Args:
            tenant: Resolved tenant context.
            status: Parsed status info.
        """
        logger.info(
            "whatsapp_status_update",
            tenant_slug=tenant.slug,
            message_id=status.id,
            status=status.status,
            recipient_id=f"***{status.recipient_id[-4:]}" if len(status.recipient_id) > 4 else "***",
        )

        # TODO: Update message status in DB (Wave 5 — conversation service)

    @staticmethod
    async def _mark_if_new(slug: str, wamid: str) -> bool:
        """Atomically check and mark a message as processed.

        Uses Redis SET NX (set if not exists) for race-safe dedup.

        Args:
            slug: Tenant slug for Redis key prefix.
            wamid: WhatsApp message ID.

        Returns:
            True if the message is new (key was set), False if duplicate.
        """
        redis = get_redis()
        key = f"{slug}:dedup:{wamid}"
        # SET NX returns True if key was set (new), False if existed (duplicate)
        was_set: bool = await redis.set(key, "1", ex=DEDUP_TTL, nx=True)
        return bool(was_set)

    @staticmethod
    async def _check_rate_limit(slug: str) -> None:
        """Check webhook rate limit for a tenant.

        Fixed-window rate limiting: INCR + EXPIRE pattern.

        Args:
            slug: Tenant slug for Redis key prefix.

        Raises:
            RateLimitExceededError: If the tenant exceeds 50 req/min.
        """
        redis = get_redis()
        key = f"{slug}:rl:webhook"

        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, RATE_LIMIT_WINDOW)

        if count > RATE_LIMIT_MAX:
            logger.warning(
                "whatsapp_webhook_rate_limited",
                tenant_slug=slug,
                count=count,
                limit=RATE_LIMIT_MAX,
            )
            raise RateLimitExceededError(
                f"Webhook rate limit exceeded for tenant {slug}",
                details={"tenant_slug": slug, "count": count, "limit": RATE_LIMIT_MAX},
            )
