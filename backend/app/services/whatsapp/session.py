"""WhatsApp session management: 24h window, deduplication, quota tracking.

Manages the Meta-mandated 24h messaging window per phone number,
tracks outbound message quotas per tenant, and provides canonical
message deduplication via Redis SET NX.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from app.core.redis import get_redis
from app.core.tenant import TenantContext

logger = structlog.get_logger()

# ── Constants ──

SESSION_TTL = 86400  # 24 hours in seconds
DEDUP_TTL = 86400  # 24 hours
QUOTA_MONTHLY_TTL = 60 * 86400  # 60 days
QUOTA_ANNUAL_TTL = 400 * 86400  # ~13 months
DEFAULT_ANNUAL_LIMIT = 100_000
WARNING_THRESHOLD = 0.80  # 80% usage triggers warning


# ── Data classes ──


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Snapshot of a WhatsApp messaging session for a phone number."""

    is_active: bool
    is_template_required: bool  # True if outside 24h window
    started_at: str | None  # ISO timestamp
    last_message_at: str | None  # ISO timestamp
    message_count: int


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    """WhatsApp messaging quota status for a tenant."""

    monthly_count: int
    annual_count: int
    annual_limit: int
    remaining: int
    is_warning: bool  # True when >= 80% of annual limit used
    is_exhausted: bool  # True when 0 remaining


# ── Service ──


class WhatsAppSessionManager:
    """Manage WhatsApp 24h messaging window, dedup, and quota tracking.

    All state is stored in Redis with tenant-scoped key prefixes.
    """

    def __init__(self) -> None:
        self.logger = logger.bind(service="whatsapp_session")

    async def get_or_create_session(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> SessionInfo:
        """Get existing session or create new one on inbound message.

        Updates last_message_at and refreshes TTL on each call.
        Creates a new session if none exists.

        Redis key: {slug}:wa_session:{phone}
        """
        redis = get_redis()
        key = f"{tenant.redis_prefix}:wa_session:{phone}"
        now = datetime.now(UTC).isoformat()

        existing = await redis.get(key)

        if existing:
            data = json.loads(existing)
            data["last_message_at"] = now
            data["message_count"] = data.get("message_count", 0) + 1
            await redis.set(key, json.dumps(data), ex=SESSION_TTL)

            self.logger.debug(
                "wa_session_updated",
                tenant=tenant.slug,
                phone_last4=phone[-4:],
                message_count=data["message_count"],
            )

            return SessionInfo(
                is_active=True,
                is_template_required=False,
                started_at=data["started_at"],
                last_message_at=data["last_message_at"],
                message_count=data["message_count"],
            )

        # New session
        data = {
            "started_at": now,
            "last_message_at": now,
            "message_count": 1,
        }
        await redis.set(key, json.dumps(data), ex=SESSION_TTL)

        self.logger.info(
            "wa_session_created",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )

        return SessionInfo(
            is_active=True,
            is_template_required=False,
            started_at=now,
            last_message_at=now,
            message_count=1,
        )

    async def get_session(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> SessionInfo:
        """Get session info without modifying it.

        Returns inactive session if no session exists (expired or never created).
        """
        redis = get_redis()
        key = f"{tenant.redis_prefix}:wa_session:{phone}"

        existing = await redis.get(key)

        if existing:
            data = json.loads(existing)
            return SessionInfo(
                is_active=True,
                is_template_required=False,
                started_at=data["started_at"],
                last_message_at=data["last_message_at"],
                message_count=data.get("message_count", 0),
            )

        return SessionInfo(
            is_active=False,
            is_template_required=True,
            started_at=None,
            last_message_at=None,
            message_count=0,
        )

    async def close_session(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> None:
        """Explicitly close a session (e.g., on conversation end)."""
        redis = get_redis()
        key = f"{tenant.redis_prefix}:wa_session:{phone}"
        await redis.delete(key)

        self.logger.info(
            "wa_session_closed",
            tenant=tenant.slug,
            phone_last4=phone[-4:],
        )

    async def increment_quota(self, tenant: TenantContext) -> None:
        """Increment monthly and annual outbound message counters.

        Redis keys:
        - {slug}:wa:quota:{YYYY-MM}  (monthly)
        - {slug}:wa:quota:annual:{YYYY}  (annual)
        """
        redis = get_redis()
        now = datetime.now(UTC)
        monthly_key = f"{tenant.redis_prefix}:wa:quota:{now.strftime('%Y-%m')}"
        annual_key = f"{tenant.redis_prefix}:wa:quota:annual:{now.strftime('%Y')}"

        pipe = redis.pipeline()
        pipe.incr(monthly_key)
        pipe.expire(monthly_key, QUOTA_MONTHLY_TTL)
        pipe.incr(annual_key)
        pipe.expire(annual_key, QUOTA_ANNUAL_TTL)
        await pipe.execute()

    async def check_quota(self, tenant: TenantContext) -> QuotaInfo:
        """Get current quota usage for the tenant.

        Returns QuotaInfo with monthly/annual counts, remaining, and warning flags.
        """
        redis = get_redis()
        now = datetime.now(UTC)
        monthly_key = f"{tenant.redis_prefix}:wa:quota:{now.strftime('%Y-%m')}"
        annual_key = f"{tenant.redis_prefix}:wa:quota:annual:{now.strftime('%Y')}"

        pipe = redis.pipeline()
        pipe.get(monthly_key)
        pipe.get(annual_key)
        results = await pipe.execute()

        monthly_count = int(results[0] or 0)
        annual_count = int(results[1] or 0)

        # Get limit from tenant config or use default
        annual_limit = DEFAULT_ANNUAL_LIMIT
        if tenant.whatsapp_config and isinstance(tenant.whatsapp_config, dict):
            annual_limit = tenant.whatsapp_config.get("annual_message_limit", DEFAULT_ANNUAL_LIMIT)

        remaining = max(0, annual_limit - annual_count)
        is_warning = annual_count >= int(annual_limit * WARNING_THRESHOLD)
        is_exhausted = remaining == 0

        return QuotaInfo(
            monthly_count=monthly_count,
            annual_count=annual_count,
            annual_limit=annual_limit,
            remaining=remaining,
            is_warning=is_warning,
            is_exhausted=is_exhausted,
        )

    async def is_duplicate_message(
        self,
        tenant: TenantContext,
        wamid: str,
    ) -> bool:
        """Check if a WhatsApp message was already processed (dedup).

        Uses atomic SET NX to check and mark in one operation.
        Redis key: {slug}:dedup:{wamid}, TTL 24h.

        Returns:
            True if duplicate (already processed), False if new.

        Note:
            This is the canonical dedup implementation. The older
            webhook.py._mark_if_new uses the same key pattern but
            with inverted return semantics. Future refactoring should
            consolidate to use this method.
        """
        redis = get_redis()
        key = f"{tenant.redis_prefix}:dedup:{wamid}"

        # SET NX returns True if key was set (new message), None/False if exists
        was_set = await redis.set(key, "1", ex=DEDUP_TTL, nx=True)

        if not was_set:
            self.logger.debug(
                "wa_message_duplicate",
                tenant=tenant.slug,
                wamid=wamid,
            )
            return True  # Duplicate

        return False  # New message
