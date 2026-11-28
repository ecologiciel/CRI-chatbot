"""Short-lived agent reply worker signal, not a delivery guarantee."""

import asyncio

import structlog
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import get_redis

HEARTBEAT_KEY = "system:agent_reply_outbox:worker_heartbeat"
HEARTBEAT_TTL_SECONDS = 45
HEARTBEAT_INTERVAL_SECONDS = 10
logger = structlog.get_logger()


async def publish_presence() -> None:
    if not get_settings().agent_reply_outbox_enabled:
        return
    async with get_session_factory()() as session:
        exists = await session.scalar(text("SELECT to_regclass('public.agent_reply_outbox_events') IS NOT NULL"))
        if not exists:
            raise RuntimeError("Agent reply table unavailable")
    await get_redis().set(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_SECONDS)


async def presence_loop() -> None:
    while True:
        try:
            await publish_presence()
        except Exception as exc:
            logger.warning("agent_reply_presence_failed", error_type=type(exc).__name__)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
