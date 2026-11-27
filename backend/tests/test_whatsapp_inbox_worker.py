from unittest.mock import AsyncMock

import pytest

import app.workers.whatsapp_inbox as worker
from app.services.whatsapp import worker_presence


@pytest.mark.asyncio
async def test_poll_does_not_execute_without_claim(monkeypatch):
    monkeypatch.setattr(worker, "claim_next", AsyncMock(return_value=None))
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_claim", execute)
    assert await worker.poll_incoming({}) == "empty"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_executes_claim_once_without_automatic_retry(monkeypatch):
    claim = object()
    monkeypatch.setattr(worker, "claim_next", AsyncMock(return_value=claim))
    execute = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "execute_claim", execute)
    assert await worker.poll_incoming({}) == "lease_lost"
    execute.assert_awaited_once_with(claim, lease_seconds=120, timeout_seconds=300)


def test_worker_uses_dedicated_queue_and_disables_automatic_retries():
    assert worker.WorkerSettings.queue_name == "arq:whatsapp-inbox"
    assert worker.WorkerSettings.max_tries == 1


@pytest.mark.asyncio
async def test_presence_is_not_refreshed_when_database_is_unavailable(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.side_effect = RuntimeError("db unavailable")
    redis = AsyncMock()
    monkeypatch.setattr(worker_presence, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(worker_presence, "get_redis", lambda: redis)
    with pytest.raises(RuntimeError):
        await worker_presence.publish_presence()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_starts_and_cancels_presence_task(monkeypatch):
    startup, shutdown = AsyncMock(), AsyncMock()
    async def complete():
        return None
    monkeypatch.setattr(worker, "infrastructure_startup", startup)
    monkeypatch.setattr(worker, "infrastructure_shutdown", shutdown)
    monkeypatch.setattr(worker, "presence_loop", complete)
    ctx = {}
    await worker.startup(ctx)
    assert "wa_presence_task" in ctx
    await worker.shutdown(ctx)
    startup.assert_awaited_once_with(ctx)
    shutdown.assert_awaited_once_with(ctx)
