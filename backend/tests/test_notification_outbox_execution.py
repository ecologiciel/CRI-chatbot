"""Fail-safe behavior of the staged durable notification executor."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.notification import outbox_execution as execution
from app.services.notification.outbox import NotificationClaim


@pytest.fixture
def setup_execution(monkeypatch):
    @asynccontextmanager
    async def db_session():
        yield object()

    tenant = SimpleNamespace(id=uuid.uuid4(), db_session=db_session)
    claim = NotificationClaim(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    claim_mock = AsyncMock(return_value=claim)
    finish_mock = AsyncMock(return_value=True)
    load_mock = AsyncMock(return_value=object())
    monkeypatch.setattr(execution, "claim_notification", claim_mock)
    monkeypatch.setattr(execution, "finish_notification", finish_mock)
    monkeypatch.setattr(execution, "quarantine_expired_notifications", AsyncMock(return_value=0))
    monkeypatch.setattr(execution, "_load_change", load_mock)
    return tenant, claim, claim_mock, finish_mock, load_mock


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("result", "expected", "code", "message_id"),
    [
        ({"status": "sent", "wamid": "wamid.123"}, "sent", "provider_accepted", "wamid.123"),
        ({"status": "sent", "wamid": None}, "uncertain", "processing_error", None),
        ({"status": "unconfirmed"}, "uncertain", "provider_unconfirmed", None),
        ({"status": "skipped", "reason": "opted_out"}, "skipped", "opted_out", None),
        ({"status": "skipped", "reason": "unknown"}, "uncertain", "unknown_skip_reason", None),
    ],
)
async def test_explicit_outcomes_are_fenced(setup_execution, result, expected, code, message_id):
    tenant, claim, _, finish, _ = setup_execution
    service = SimpleNamespace(send_notification=AsyncMock(return_value=result))
    assert await execution.process_one_notification(tenant, service) == expected
    service.send_notification.assert_awaited_once()
    assert service.send_notification.await_args.kwargs == {"durable": True}
    assert finish.await_args.args[1:] == (tenant.id, claim)
    assert finish.await_args.kwargs == {
        "outcome": expected,
        "outcome_code": code,
        "provider_message_id": message_id,
    }


@pytest.mark.asyncio()
async def test_provider_exception_is_uncertain_and_never_retried(setup_execution):
    tenant, _, _, finish, _ = setup_execution
    service = SimpleNamespace(send_notification=AsyncMock(side_effect=RuntimeError("private")))
    assert await execution.process_one_notification(tenant, service) == "uncertain"
    service.send_notification.assert_awaited_once()
    assert finish.await_args.kwargs["outcome_code"] == "processing_error"


@pytest.mark.asyncio()
async def test_timeout_is_uncertain_and_never_retried(setup_execution):
    tenant, _, _, finish, _ = setup_execution

    async def stalled(*args, **kwargs):
        await asyncio.sleep(1)

    service = SimpleNamespace(send_notification=AsyncMock(side_effect=stalled))
    assert (
        await execution.process_one_notification(tenant, service, timeout_seconds=0.01)
        == "uncertain"
    )
    service.send_notification.assert_awaited_once()
    assert finish.await_args.kwargs["outcome_code"] == "processing_timeout"


@pytest.mark.asyncio()
async def test_missing_history_does_not_send(setup_execution):
    tenant, _, _, finish, load = setup_execution
    load.return_value = None
    service = SimpleNamespace(send_notification=AsyncMock())
    assert await execution.process_one_notification(tenant, service) == "uncertain"
    service.send_notification.assert_not_awaited()
    assert finish.await_args.kwargs["outcome_code"] == "history_unavailable"


@pytest.mark.asyncio()
async def test_lost_lease_is_not_misreported_as_success(setup_execution):
    tenant, _, _, finish, _ = setup_execution
    finish.return_value = False
    service = SimpleNamespace(
        send_notification=AsyncMock(return_value={"status": "sent", "wamid": "wamid.1"})
    )
    assert await execution.process_one_notification(tenant, service) == "lease_lost"
    service.send_notification.assert_awaited_once()
