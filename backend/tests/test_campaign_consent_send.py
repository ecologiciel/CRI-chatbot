from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.enums import OptInStatus, RecipientStatus
from app.workers import campaign as worker


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [OptInStatus.opted_out, OptInStatus.pending])
async def test_campaign_does_not_send_when_consent_is_no_longer_active(monkeypatch, status):
    contact = SimpleNamespace(opt_in_status=status, phone="212600000001")
    result = MagicMock()
    result.scalar_one_or_none.return_value = contact
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def db_session():
        yield session

    tenant = SimpleNamespace(db_session=db_session)
    campaign = SimpleNamespace(
        id=uuid4(), variable_mapping={}, template_name="demo", template_language="fr"
    )
    recipient = SimpleNamespace(id=uuid4(), contact_id=uuid4())
    sender = SimpleNamespace(send_template=AsyncMock())
    service = SimpleNamespace(_sender=sender, resolve_variables=MagicMock())
    update = AsyncMock()
    monkeypatch.setattr(worker, "_update_recipient_status", update)
    assert not await worker._send_single_recipient(
        tenant, campaign, recipient, service, AsyncMock()
    )
    sender.send_template.assert_not_awaited()
    update.assert_awaited_once_with(
        tenant, recipient.id, RecipientStatus.failed, error_message="Contact consent is not active"
    )


@pytest.mark.asyncio
async def test_campaign_keeps_contact_lock_during_send(monkeypatch):
    in_transaction = False
    contact = SimpleNamespace(opt_in_status=OptInStatus.opted_in, phone="212600000001")
    result = MagicMock()
    result.scalar_one_or_none.return_value = contact
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def db_session():
        nonlocal in_transaction
        in_transaction = True
        try:
            yield session
        finally:
            in_transaction = False

    async def send(**kwargs):
        assert in_transaction
        return "wamid.synthetic"

    tenant = SimpleNamespace(db_session=db_session)
    campaign = SimpleNamespace(
        id=uuid4(), variable_mapping={}, template_name="demo", template_language="fr"
    )
    recipient = SimpleNamespace(id=uuid4(), contact_id=uuid4())
    service = SimpleNamespace(
        _sender=SimpleNamespace(send_template=AsyncMock(side_effect=send)),
        resolve_variables=MagicMock(return_value=[]),
    )
    monkeypatch.setattr(worker, "_update_recipient_status", AsyncMock())
    assert await worker._send_single_recipient(tenant, campaign, recipient, service, AsyncMock())
    assert session.execute.await_args.args[0]._for_update_arg is not None
