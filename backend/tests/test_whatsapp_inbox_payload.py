import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.services.whatsapp.inbox_leases import InboxClaim
from app.services.whatsapp.inbox_payload import decrypt_claim


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
        sender_fingerprint="a" * 64,
    )


@pytest.fixture
def payload():
    return {
        "phone_number_id": "123",
        "message": {"id": "wamid.1", "from": "212600000000", "timestamp": "123", "type": "text"},
        "contacts": [{"wa_id": "212600000000", "profile": {}}],
    }


@pytest.mark.asyncio
async def test_decryption_binds_claim_context(claim, payload):
    cipher = AsyncMock()
    cipher.decrypt.return_value = json.dumps(payload).encode()
    cipher.whatsapp_sender_fingerprint.return_value = "a" * 64
    result = await decrypt_claim(claim, cipher)
    assert result.message.id == claim.provider_message_id
    assert result.contacts[0].wa_id == result.message.from_
    assert cipher.decrypt.await_args.kwargs == {
        "tenant_id": claim.tenant_id,
        "purpose": "wa_inbox",
        "record_id": claim.id,
    }
    assert cipher.decrypt.await_args.args[0].version == claim.key_version


@pytest.mark.asyncio
async def test_claim_rejects_conversation_fingerprint_mismatch(claim, payload):
    cipher = AsyncMock()
    cipher.decrypt.return_value = json.dumps(payload).encode()
    cipher.whatsapp_sender_fingerprint.return_value = "b" * 64
    with pytest.raises(ValueError, match="conversation identifier mismatch"):
        await decrypt_claim(claim, cipher)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["channel", "message", "contact", "contacts"])
async def test_mismatched_claim_is_rejected(claim, payload, field):
    if field == "channel":
        payload["phone_number_id"] = "456"
    elif field == "message":
        payload["message"]["id"] = "wamid.other"
    elif field == "contact":
        payload["contacts"][0]["wa_id"] = "212611111111"
    else:
        payload["contacts"] = None
    cipher = AsyncMock()
    cipher.decrypt.return_value = json.dumps(payload).encode()
    cipher.whatsapp_sender_fingerprint.return_value = "a" * 64
    with pytest.raises(ValueError):
        await decrypt_claim(claim, cipher)
