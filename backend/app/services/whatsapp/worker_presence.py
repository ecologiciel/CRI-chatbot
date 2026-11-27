"""Short-lived worker presence signal; not a provider delivery guarantee."""

import asyncio

import structlog
from sqlalchemy import text

from app.core.database import get_session_factory
from app.core.redis import get_redis

HEARTBEAT_KEY = "system:whatsapp_inbox:worker_heartbeat"
HEARTBEAT_TTL_SECONDS = 45
HEARTBEAT_INTERVAL_SECONDS = 10
logger = structlog.get_logger()


async def publish_presence() -> None:
    """Publish only after both the database and Redis are reachable."""
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    await get_redis().set(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_SECONDS)


async def presence_loop() -> None:
    while True:
        try:
            await publish_presence()
        except Exception as exc:
            logger.warning("wa_worker_presence_failed", error_type=type(exc).__name__)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
