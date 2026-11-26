import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

import app.services.whatsapp.inbox_execution as execution
from app.services.whatsapp.handler import HandlingOutcome
from app.services.whatsapp.inbox_leases import InboxClaim


@pytest.fixture
def claim():
    return InboxClaim(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        phone_number_id="123",
        provider_message_id="wamid.1",
        key_version=1,
        ciphertext="ciphertext",
        lease_token=uuid.uuid4(),
        lease_until=datetime.now(UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [HandlingOutcome.accepted, HandlingOutcome.uncertain])
async def test_fenced_completion_reflects_handler_outcome(monkeypatch, claim, outcome):
    monkeypatch.setattr(execution, "_process", AsyncMock(return_value=outcome))
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr(execution, "finish_claim", finish)
    assert await execution.execute_claim(claim)
    finish.assert_awaited_once_with(
        claim.id, claim.lease_token, uncertain=outcome != HandlingOutcome.accepted
    )


@pytest.mark.asyncio
async def test_lost_lease_quarantines_without_retry(monkeypatch, claim):
    started = asyncio.Event()

    async def process(_claim):
        started.set()
        await asyncio.Event().wait()

    async def lost_lease(_claim, _seconds):
        await started.wait()
        raise RuntimeError("lease lost")

    finish = AsyncMock(return_value=False)
    monkeypatch.setattr(execution, "_process", process)
    monkeypatch.setattr(execution, "_heartbeat", lost_lease)
    monkeypatch.setattr(execution, "finish_claim", finish)
    assert not await execution.execute_claim(claim)
    finish.assert_awaited_once_with(claim.id, claim.lease_token, uncertain=True)


@pytest.mark.asyncio
async def test_handler_exception_is_uncertain(monkeypatch, claim):
    monkeypatch.setattr(execution, "_process", AsyncMock(side_effect=RuntimeError("failure")))
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr(execution, "finish_claim", finish)
    assert await execution.execute_claim(claim)
    finish.assert_awaited_once_with(claim.id, claim.lease_token, uncertain=True)
