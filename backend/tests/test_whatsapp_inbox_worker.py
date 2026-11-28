from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.workers.whatsapp_inbox as worker
from app.services.whatsapp import worker_presence


@pytest.fixture(autouse=True)
def enable_worker_by_default(monkeypatch):
    settings = MagicMock(whatsapp_durable_inbox_enabled=True)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_presence, "get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_disabled_worker_does_not_claim_process_status_or_publish(monkeypatch):
    disabled = MagicMock(whatsapp_durable_inbox_enabled=False)
    monkeypatch.setattr(worker, "get_settings", lambda: disabled)
    monkeypatch.setattr(worker_presence, "get_settings", lambda: disabled)
    claim, run_status, redis = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker, "claim_next", claim)
    monkeypatch.setattr(worker, "run_status_batch", run_status)
    monkeypatch.setattr(worker_presence, "get_redis", lambda: redis)
    assert await worker.poll_incoming({}) == "disabled"
    assert await worker.drain_incoming({}) == {"claimed": 0, "lease_lost": 0, "disabled": 1}
    assert await worker.poll_statuses({}) == {"disabled": 1}
    await worker_presence.publish_presence()
    claim.assert_not_awaited()
    run_status.assert_not_awaited()
    redis.set.assert_not_awaited()


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
async def test_drain_stops_at_empty_and_reports_lost_lease(monkeypatch):
    poll = AsyncMock(side_effect=["finalized", "lease_lost", "empty"])
    monkeypatch.setattr(worker, "poll_incoming", poll)
    assert await worker.drain_incoming({}) == {"claimed": 2, "lease_lost": 1}
    assert poll.await_count == 3


@pytest.mark.asyncio
async def test_drain_respects_batch_and_time_limits(monkeypatch):
    poll = AsyncMock(return_value="finalized")
    monkeypatch.setattr(worker, "poll_incoming", poll)
    with patch("app.workers.whatsapp_inbox.monotonic", return_value=0):
        assert await worker.drain_incoming({}) == {"claimed": 10, "lease_lost": 0}
    assert poll.await_count == 10
    poll.reset_mock()
    with patch("app.workers.whatsapp_inbox.monotonic", side_effect=[0, 31]):
        assert await worker.drain_incoming({}) == {"claimed": 1, "lease_lost": 0}
    poll.assert_awaited_once()


@pytest.mark.asyncio
async def test_presence_is_not_refreshed_when_database_is_unavailable(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.side_effect = RuntimeError("db unavailable")
    redis = AsyncMock()
    monkeypatch.setattr(worker_presence, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(worker_presence, "get_redis", lambda: redis)
    with pytest.raises(RuntimeError):
        await worker_presence.publish_presence()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_presence_requires_both_durable_tables(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = False
    redis = AsyncMock()
    monkeypatch.setattr(worker_presence, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(worker_presence, "get_redis", lambda: redis)
    with pytest.raises(RuntimeError, match="tables unavailable"):
        await worker_presence.publish_presence()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_presence_published_only_when_enabled_and_tables_exist(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = True
    redis = AsyncMock()
    monkeypatch.setattr(worker_presence, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(worker_presence, "get_redis", lambda: redis)
    await worker_presence.publish_presence()
    redis.set.assert_awaited_once_with(
        worker_presence.HEARTBEAT_KEY, "1", ex=worker_presence.HEARTBEAT_TTL_SECONDS,
    )


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
