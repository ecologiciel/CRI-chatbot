"""Stable, opaque sender grouping across encryption key rotations."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import CRIDecryptionError
from app.services.crypto.versioned_envelope import VersionedEnvelopeService


@pytest.mark.asyncio
async def test_sender_fingerprint_is_stable_and_scoped():
    service = VersionedEnvelopeService(None, "00" * 32)
    service._key = AsyncMock(return_value=(1, b"a" * 32))
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    args = {"tenant_id": tenant_a, "channel_id": "123", "sender_id": "212600000000"}
    first = await service.whatsapp_sender_fingerprint(**args)
    assert first == await service.whatsapp_sender_fingerprint(**args)
    assert first != await service.whatsapp_sender_fingerprint(**{**args, "tenant_id": tenant_b})
    assert first != await service.whatsapp_sender_fingerprint(**{**args, "channel_id": "456"})
    assert first != await service.whatsapp_sender_fingerprint(**{**args, "sender_id": "212611111111"})
    assert len(first) == 64 and "212600000000" not in first
    assert all(call.args[1] == 1 for call in service._key.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,sender", [("", "1"), ("1", ""), ("x" * 33, "1"), ("1", "x" * 129)])
async def test_sender_fingerprint_rejects_invalid_identifiers(channel, sender):
    service = VersionedEnvelopeService(None, "00" * 32)
    service._key = AsyncMock()
    with pytest.raises(ValueError):
        await service.whatsapp_sender_fingerprint(tenant_id=uuid.uuid4(), channel_id=channel, sender_id=sender)
    service._key.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_stable_key_does_not_fall_back_to_current_key():
    service = VersionedEnvelopeService(None, "00" * 32)
    service._key = AsyncMock(side_effect=CRIDecryptionError("unavailable"))
    tenant_id = uuid.uuid4()
    with pytest.raises(CRIDecryptionError):
        await service.whatsapp_sender_fingerprint(tenant_id=tenant_id, channel_id="123", sender_id="456")
    service._key.assert_awaited_once_with(tenant_id, 1)
