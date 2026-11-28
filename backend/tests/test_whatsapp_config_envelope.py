"""Channel credential envelopes use real AES-GCM and never expose secrets."""

import base64
import copy
import secrets
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.exceptions import CRIDecryptionError, CRIEncryptionError
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import open_channel_config, seal_channel_config


@pytest.fixture
def cipher():
    master, data_key = secrets.token_bytes(32), secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    row = SimpleNamespace(key_version=1, encrypted_key=nonce + AESGCM(master).encrypt(nonce, data_key, None))
    result = MagicMock()
    result.one_or_none.return_value = row
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def factory():
        yield db

    return VersionedEnvelopeService(factory, master.hex())


@pytest.mark.asyncio
async def test_config_round_trip_hides_all_except_routing_and_binds_tenant(cipher):
    tenant = uuid.uuid4()
    config = {
        "phone_number_id": "123456789", "access_token": "synthetic-access-secret",
        "verify_token": "synthetic-verify-secret", "arbitrary": {"private": "synthetic-extra"},
        "notification_templates": {"status": "fixture"}, "annual_message_limit": 1000,
    }
    first = await seal_channel_config(tenant, config, cipher)
    second = await seal_channel_config(tenant, config, cipher)
    assert first != second
    assert set(first) == {"phone_number_id", "_format", "_envelope"}
    assert first["phone_number_id"] == "123456789"
    assert all(value not in repr(first) for value in ("synthetic-access-secret", "synthetic-verify-secret", "synthetic-extra"))
    assert await open_channel_config(tenant, first, cipher) == config
    with pytest.raises(CRIDecryptionError):
        await open_channel_config(uuid.uuid4(), first, cipher)

    for change in ("phone", "ciphertext", "version", "extra", "format"):
        altered = copy.deepcopy(first)
        if change == "phone":
            altered["phone_number_id"] = "999"
        elif change == "ciphertext":
            raw = bytearray(base64.b64decode(altered["_envelope"]["ciphertext"]))
            raw[-1] ^= 1
            altered["_envelope"]["ciphertext"] = base64.b64encode(raw).decode()
        elif change == "version":
            altered["_envelope"]["version"] = True
        elif change == "extra":
            altered["access_token"] = "plaintext"
        else:
            altered["_format"] = "unknown"
        with pytest.raises(CRIDecryptionError):
            await open_channel_config(tenant, altered, cipher)


@pytest.mark.asyncio
async def test_refuses_plaintext_invalid_and_oversized_configs(cipher):
    tenant = uuid.uuid4()
    with pytest.raises(CRIDecryptionError):
        await open_channel_config(tenant, {"phone_number_id": "123", "access_token": "plaintext"}, cipher)
    for config in (
        {"phone_number_id": "12x"},
        {"phone_number_id": "123", "_envelope": "spoofed"},
        {"phone_number_id": "123", "extra": "x" * 140_000},
        {"phone_number_id": "123", "extra": float("nan")},
        {"phone_number_id": "123", "extra": {1: "ambiguous-key"}},
    ):
        with pytest.raises(CRIEncryptionError):
            await seal_channel_config(tenant, config, cipher)
