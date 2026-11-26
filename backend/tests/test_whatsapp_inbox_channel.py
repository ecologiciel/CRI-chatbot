import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import TenantInactiveError
from app.core.tenant import TenantContext
from app.models.enums import TenantStatus
from app.services.whatsapp.inbox_channel import protect_claim_channel
from app.services.whatsapp.inbox_leases import InboxClaim


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_claim_pins_channel_and_rejects_reassignment(monkeypatch, changed):
    import app.services.whatsapp.inbox_channel as module

    tenant_id = uuid.uuid4()
    claim = InboxClaim(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number_id="123",
        provider_message_id="wamid.1",
        key_version=1,
        ciphertext="encrypted",
        lease_token=uuid.uuid4(),
        lease_until=datetime.now(UTC),
    )
    tenant = TenantContext(tenant_id, "onssa", "ONSSA", "active", {"phone_number_id": "123"})
    row = SimpleNamespace(
        id=tenant_id,
        slug="onssa",
        name="ONSSA",
        status=TenantStatus.active,
        whatsapp_config={"phone_number_id": "456" if changed else "123"},
    )
    state = {"lifecycle": False, "db": False}

    @asynccontextmanager
    async def lifecycle(_tenant):
        state["lifecycle"] = True
        try:
            yield
        finally:
            state["lifecycle"] = False

    @asynccontextmanager
    async def session_context():
        state["db"] = True
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        session = SimpleNamespace(execute=AsyncMock(return_value=result))
        try:
            yield session
        finally:
            state["db"] = False

    monkeypatch.setattr(
        module.TenantResolver, "from_tenant_id_header", AsyncMock(return_value=tenant)
    )
    monkeypatch.setattr(module, "protect_ingestion", lifecycle)
    monkeypatch.setattr(module, "get_session_factory", lambda: session_context)
    if changed:
        with pytest.raises(TenantInactiveError):
            async with protect_claim_channel(claim):
                pytest.fail("Changed channel was accepted")
    else:
        async with protect_claim_channel(claim) as current:
            assert current.id == tenant_id
            assert state == {"lifecycle": True, "db": True}
    assert state == {"lifecycle": False, "db": False}
