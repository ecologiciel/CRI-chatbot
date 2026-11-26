"""Versioned encryption must remain readable after rotation and bind context."""

import base64
import secrets
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.exceptions import CRIDecryptionError
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService


def wrapped(master: bytes, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(master).encrypt(nonce, key, None)


@pytest.mark.asyncio
async def test_historical_key_and_context_binding():
    master = secrets.token_bytes(32)
    key_one, key_two = secrets.token_bytes(32), secrets.token_bytes(32)
    tenant, record = uuid.uuid4(), uuid.uuid4()
    current = SimpleNamespace(key_version=1, encrypted_key=wrapped(master, key_one))
    historical = current
    result = MagicMock()
    result.one_or_none.return_value = current
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def factory():
        yield db

    service = VersionedEnvelopeService(factory, master.hex())
    envelope = await service.encrypt(
        b"message prive", tenant_id=tenant, purpose="wa_inbox", record_id=record
    )
    assert envelope.version == 1
    result.one_or_none.return_value = historical
    assert (
        await service.decrypt(envelope, tenant_id=tenant, purpose="wa_inbox", record_id=record)
        == b"message prive"
    )
    parameters = db.execute.await_args.args[0].compile().params.values()
    assert tenant in parameters
    assert envelope.version in parameters

    for other_tenant, purpose, other_record in (
        (uuid.uuid4(), "wa_inbox", record),
        (tenant, "other", record),
        (tenant, "wa_inbox", uuid.uuid4()),
    ):
        with pytest.raises(CRIDecryptionError):
            await service.decrypt(
                envelope, tenant_id=other_tenant, purpose=purpose, record_id=other_record
            )

    result.one_or_none.return_value = SimpleNamespace(
        key_version=2, encrypted_key=wrapped(master, key_two)
    )
    next_envelope = await service.encrypt(
        b"message prive", tenant_id=tenant, purpose="wa_inbox", record_id=record
    )
    assert next_envelope.version == 2
    result.one_or_none.return_value = historical
    assert (
        await service.decrypt(envelope, tenant_id=tenant, purpose="wa_inbox", record_id=record)
        == b"message prive"
    )

    raw = bytearray(base64.b64decode(envelope.ciphertext))
    raw[-1] ^= 1
    with pytest.raises(CRIDecryptionError):
        await service.decrypt(
            VersionedEnvelope(1, base64.b64encode(raw).decode()),
            tenant_id=tenant,
            purpose="wa_inbox",
            record_id=record,
        )
