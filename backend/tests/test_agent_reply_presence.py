from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.escalation.reply_presence import (
    HEARTBEAT_KEY,
    HEARTBEAT_TTL_SECONDS,
    publish_presence,
)


@pytest.mark.asyncio
async def test_disabled_worker_does_not_publish_presence():
    with (patch("app.services.escalation.reply_presence.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=False)),
          patch("app.services.escalation.reply_presence.get_session_factory") as factory,
          patch("app.services.escalation.reply_presence.get_redis") as redis):
        await publish_presence()
    factory.assert_not_called()
    redis.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("table_exists", [True, False])
async def test_presence_requires_database_table(table_exists):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = table_exists
    redis = AsyncMock()
    with (patch("app.services.escalation.reply_presence.get_settings", return_value=MagicMock(agent_reply_outbox_enabled=True)),
          patch("app.services.escalation.reply_presence.get_session_factory", return_value=lambda: session),
          patch("app.services.escalation.reply_presence.get_redis", return_value=redis)):
        if table_exists:
            await publish_presence()
        else:
            with pytest.raises(RuntimeError):
                await publish_presence()
    if table_exists:
        redis.set.assert_awaited_once_with(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_SECONDS)
    else:
        redis.set.assert_not_awaited()
