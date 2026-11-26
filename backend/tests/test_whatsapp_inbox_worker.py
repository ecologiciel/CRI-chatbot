from unittest.mock import AsyncMock

import pytest

import app.workers.whatsapp_inbox as worker


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
