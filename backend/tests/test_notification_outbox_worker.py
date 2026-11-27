"""Cutover guards and isolation for the staged notification worker."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers import notification_outbox as worker


@pytest.mark.asyncio()
async def test_worker_disabled_by_default_never_connects(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(dossier_notification_outbox_enabled=False)
    )
    resolver = AsyncMock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(worker.TenantResolver, "from_slug", resolver)
    assert await worker.process_tenant_outbox("a") == "disabled"
    assert await worker.poll_outboxes({}) == {"disabled": 1}
    resolver.assert_not_awaited()


@pytest.mark.asyncio()
async def test_nonempty_legacy_queue_prevents_new_send(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(dossier_notification_outbox_enabled=True)
    )
    tenant = SimpleNamespace(slug="a")
    monkeypatch.setattr(worker.TenantResolver, "from_slug", AsyncMock(return_value=tenant))
    redis = SimpleNamespace(llen=AsyncMock(return_value=1))
    monkeypatch.setattr(worker, "get_redis", lambda: redis)
    process = AsyncMock()
    monkeypatch.setattr(worker, "process_one_notification", process)
    assert await worker.process_tenant_outbox("a") == "legacy_queue_present"
    process.assert_not_awaited()
    redis.llen.assert_awaited_once_with("a:notification:dossier_changes")


@pytest.mark.asyncio()
async def test_unknown_legacy_queue_state_fails_closed(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(dossier_notification_outbox_enabled=True)
    )
    monkeypatch.setattr(
        worker.TenantResolver, "from_slug", AsyncMock(return_value=SimpleNamespace(slug="a"))
    )
    monkeypatch.setattr(
        worker, "get_redis", lambda: SimpleNamespace(llen=AsyncMock(side_effect=ConnectionError()))
    )
    process = AsyncMock()
    monkeypatch.setattr(worker, "process_one_notification", process)
    with pytest.raises(ConnectionError):
        await worker.process_tenant_outbox("a")
    process.assert_not_awaited()


@pytest.mark.asyncio()
async def test_empty_legacy_queue_executes_one_intent(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(dossier_notification_outbox_enabled=True)
    )
    tenant = SimpleNamespace(slug="a")
    monkeypatch.setattr(worker.TenantResolver, "from_slug", AsyncMock(return_value=tenant))
    monkeypatch.setattr(
        worker, "get_redis", lambda: SimpleNamespace(llen=AsyncMock(return_value=0))
    )
    service = object()
    monkeypatch.setattr(worker, "get_notification_service", lambda: service)
    process = AsyncMock(return_value="sent")
    monkeypatch.setattr(worker, "process_one_notification", process)
    assert await worker.process_tenant_outbox("a") == "sent"
    process.assert_awaited_once_with(tenant, service)


@pytest.mark.asyncio()
async def test_one_tenant_failure_does_not_block_other_tenants(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(dossier_notification_outbox_enabled=True)
    )
    result = MagicMock()
    result.scalars.return_value = ["a", "b"]
    session = AsyncMock()
    session.execute.return_value = result
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    process = AsyncMock(side_effect=[RuntimeError("sensitive"), "sent"])
    monkeypatch.setattr(worker, "process_tenant_outbox", process)
    assert await worker.poll_outboxes({}) == {"error": 1, "sent": 1}
    assert process.await_count == 2
