"""Channel credential envelopes use real AES-GCM and never expose secrets."""

import base64
import copy
import secrets
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.exceptions import CRIDecryptionError, CRIEncryptionError, TenantProvisioningError
from app.schemas.tenant import TenantCreate
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.tenant.provisioning import TenantProvisioningService
from app.services.whatsapp.config_envelope import (
    load_channel_config,
    open_channel_config,
    prepare_channel_config_write,
    seal_channel_config,
)


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


@pytest.mark.asyncio
async def test_transition_accepts_plaintext_only_when_explicitly_permitted(cipher):
    tenant = uuid.uuid4()
    legacy = {"phone_number_id": "123", "access_token": "synthetic"}
    assert await load_channel_config(tenant, legacy, cipher) == legacy
    with pytest.raises(CRIDecryptionError):
        await load_channel_config(tenant, legacy, cipher, require_encryption=True)
    sealed = await seal_channel_config(tenant, legacy, cipher)
    assert await load_channel_config(tenant, sealed, cipher, require_encryption=True) == legacy
    with pytest.raises(CRIDecryptionError):
        await load_channel_config(tenant, sealed, None)
    with pytest.raises(CRIDecryptionError):
        await load_channel_config(tenant, {"phone_number_id": "123", "_format": "damaged"}, cipher)
    assert await load_channel_config(tenant, None, cipher, require_encryption=True) is None


@pytest.mark.asyncio
async def test_updates_never_downgrade_sealed_config(cipher):
    tenant = uuid.uuid4()
    original = {"phone_number_id": "123", "access_token": "old"}
    replacement = {"phone_number_id": "123", "access_token": "synthetic-replacement-secret"}
    sealed = await seal_channel_config(tenant, original, cipher)
    updated = await prepare_channel_config_write(tenant, replacement, sealed, cipher)
    assert updated and "synthetic-replacement-secret" not in repr(updated)
    assert await open_channel_config(tenant, updated, cipher) == replacement
    with pytest.raises(CRIEncryptionError):
        await prepare_channel_config_write(tenant, replacement, sealed, None)
    with pytest.raises(CRIEncryptionError):
        await prepare_channel_config_write(tenant, replacement, original, None, require_encryption=True)
    assert await prepare_channel_config_write(tenant, replacement, original, cipher) == replacement
    assert await prepare_channel_config_write(tenant, None, sealed, None) is None


@pytest.mark.asyncio
async def test_strict_provisioning_without_key_fails_before_creating_channel():
    payload = TenantCreate(
        name="Fixture", slug="fixture", region="Fixture",
        whatsapp_config={"phone_number_id": "123", "access_token": "synthetic", "verify_token": "synthetic"},
    )
    service = TenantProvisioningService()
    service._create_tenant_record = AsyncMock()
    with patch("app.services.tenant.provisioning.get_settings", return_value=SimpleNamespace(whatsapp_config_require_encryption=True, kms_master_key="")):
        with pytest.raises(TenantProvisioningError):
            await service.provision_tenant(payload)
    service._create_tenant_record.assert_not_awaited()
