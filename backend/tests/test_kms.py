"""Tests for KMS (Key Management Service) — envelope encryption.

Tests cover:
- Model and service imports
- Pure AES-256-GCM crypto round-trips (no mocks)
- Envelope encryption (master key wraps data key wraps data)
- Invalid key handling
- Tampered ciphertext detection
- Schema security (no encrypted_key exposure)
- Service methods with mocked DB/Redis
"""

from __future__ import annotations

import base64
import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ── Model & Service imports ──


def test_tenant_key_model_import():
    """TenantKey model is importable with correct table config."""
    from app.models.tenant_key import TenantKey

    assert TenantKey.__tablename__ == "tenant_keys"
    assert TenantKey.__table_args__[-1] == {"schema": "public"}


def test_kms_service_import():
    """KMSService class is importable."""
    from app.services.crypto.kms import KMSService

    assert KMSService is not None
    assert hasattr(KMSService, "encrypt")
    assert hasattr(KMSService, "decrypt")
    assert hasattr(KMSService, "rotate_key")
    assert hasattr(KMSService, "generate_tenant_key")


# ── Pure crypto tests (no DB, no Redis) ──


def test_aesgcm_encrypt_decrypt_roundtrip():
    """AES-256-GCM encrypt → decrypt returns original plaintext."""
    key = secrets.token_bytes(32)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)

    plaintext = "CIN: AB123456 — données sensibles"
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)

    assert decrypted.decode("utf-8") == plaintext


def test_envelope_encryption_roundtrip():
    """Full envelope encryption: master wraps data key, data key wraps payload."""
    master_key = secrets.token_bytes(32)
    data_key = secrets.token_bytes(32)

    # Master key wraps data key
    master_aesgcm = AESGCM(master_key)
    nonce_master = secrets.token_bytes(12)
    wrapped_data_key = master_aesgcm.encrypt(nonce_master, data_key, None)

    # Unwrap data key
    unwrapped_data_key = master_aesgcm.decrypt(nonce_master, wrapped_data_key, None)
    assert unwrapped_data_key == data_key

    # Data key encrypts payload
    data_aesgcm = AESGCM(data_key)
    nonce_data = secrets.token_bytes(12)
    plaintext = "N° dossier: RSK-2026-001234"
    ciphertext = data_aesgcm.encrypt(nonce_data, plaintext.encode("utf-8"), None)

    # Data key decrypts payload
    decrypted = data_aesgcm.decrypt(nonce_data, ciphertext, None)
    assert decrypted.decode("utf-8") == plaintext


def test_different_nonces_produce_different_ciphertexts():
    """Same plaintext + same key with different nonces → different ciphertexts."""
    key = secrets.token_bytes(32)
    aesgcm = AESGCM(key)
    plaintext = b"test data"

    nonce1 = secrets.token_bytes(12)
    nonce2 = secrets.token_bytes(12)
    ct1 = aesgcm.encrypt(nonce1, plaintext, None)
    ct2 = aesgcm.encrypt(nonce2, plaintext, None)

    assert ct1 != ct2  # Nonces ensure distinct ciphertexts


def test_tampered_ciphertext_raises_invalid_tag():
    """GCM detects tampered ciphertext — raises InvalidTag."""
    from cryptography.exceptions import InvalidTag

    key = secrets.token_bytes(32)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, b"sensitive data", None)

    # Tamper with one byte
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    tampered = bytes(tampered)

    with pytest.raises(InvalidTag):
        aesgcm.decrypt(nonce, tampered, None)


def test_wrong_key_raises_invalid_tag():
    """Decryption with wrong key fails with InvalidTag."""
    from cryptography.exceptions import InvalidTag

    key1 = secrets.token_bytes(32)
    key2 = secrets.token_bytes(32)
    aesgcm1 = AESGCM(key1)
    aesgcm2 = AESGCM(key2)
    nonce = secrets.token_bytes(12)

    ciphertext = aesgcm1.encrypt(nonce, b"secret", None)

    with pytest.raises(InvalidTag):
        aesgcm2.decrypt(nonce, ciphertext, None)


# ── KMSService initialization ──


def test_kms_invalid_master_key_short():
    """Master key shorter than 64 hex chars → ValueError."""
    from app.services.crypto.kms import KMSService

    with pytest.raises(ValueError, match="32 bytes"):
        KMSService(MagicMock(), MagicMock(), "abcd")


def test_kms_invalid_master_key_not_hex():
    """Non-hex master key → ValueError."""
    from app.services.crypto.kms import KMSService

    with pytest.raises(ValueError):
        KMSService(MagicMock(), MagicMock(), "zz" * 32)


def test_kms_valid_master_key():
    """Valid 64-hex-char master key initializes successfully."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    kms = KMSService(MagicMock(), MagicMock(), master_hex)
    assert kms.NONCE_SIZE == 12
    assert kms.CACHE_TTL == 300


# ── Schema security ──


def test_tenant_key_schema_no_encrypted_key_leak():
    """TenantKeyRead schema does NOT expose encrypted_key."""
    from app.schemas.crypto import TenantKeyRead

    fields = TenantKeyRead.model_fields
    assert "encrypted_key" not in fields
    # Verify expected fields ARE present
    assert "id" in fields
    assert "tenant_id" in fields
    assert "algorithm" in fields
    assert "key_version" in fields
    assert "is_active" in fields


def test_encrypt_response_schema():
    """EncryptResponse has ciphertext field."""
    from app.schemas.crypto import EncryptResponse

    resp = EncryptResponse(ciphertext="abc123==")
    assert resp.ciphertext == "abc123=="


def test_decrypt_response_schema():
    """DecryptResponse has plaintext field."""
    from app.schemas.crypto import DecryptResponse

    resp = DecryptResponse(plaintext="hello")
    assert resp.plaintext == "hello"


# ── KMSService methods (mocked DB/Redis) ──


@pytest.mark.asyncio
async def test_generate_tenant_key():
    """generate_tenant_key inserts a TenantKey row via session."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)
    mock_redis = AsyncMock()

    kms = KMSService(mock_factory, mock_redis, master_hex)
    tenant_id = uuid.uuid4()

    await kms.generate_tenant_key(tenant_id)

    # Verify a TenantKey was added to the session
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert added_obj.tenant_id == tenant_id
    assert added_obj.algorithm == "AES-256-GCM"
    assert added_obj.key_version == 1
    assert added_obj.is_active is True
    assert len(added_obj.encrypted_key) > 12 + 16  # nonce + tag minimum
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_data_key_cache_hit():
    """When Redis has cached key, no DB query is made."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    data_key = secrets.token_bytes(32)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=data_key.hex())
    mock_factory = MagicMock()

    kms = KMSService(mock_factory, mock_redis, master_hex)
    result = await kms._get_data_key("test-tenant")

    assert result == data_key
    mock_redis.get.assert_called_once_with("test-tenant:kms:data_key")
    # Factory should NOT be called (no DB hit)
    mock_factory.assert_not_called()


@pytest.mark.asyncio
async def test_get_data_key_cache_miss():
    """On cache miss, loads from DB, decrypts, and caches."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    master_key = bytes.fromhex(master_hex)
    data_key = secrets.token_bytes(32)

    # Encrypt the data key with master (simulating what's stored in DB)
    master_aesgcm = AESGCM(master_key)
    nonce = secrets.token_bytes(12)
    wrapped = master_aesgcm.encrypt(nonce, data_key, None)
    stored_blob = nonce + wrapped

    # Mock Redis: cache miss
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    # Mock DB session with a result containing the encrypted blob
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored_blob
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_factory = MagicMock(return_value=mock_session)

    kms = KMSService(mock_factory, mock_redis, master_hex)
    result = await kms._get_data_key("test-tenant")

    assert result == data_key
    # Verify cache was populated
    mock_redis.set.assert_called_once_with("test-tenant:kms:data_key", data_key.hex(), ex=300)


@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip_service():
    """Full service-level encrypt → decrypt round-trip with mocked infra."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    data_key = secrets.token_bytes(32)

    # Mock _get_data_key to return a known data key
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=data_key.hex())
    mock_factory = MagicMock()

    kms = KMSService(mock_factory, mock_redis, master_hex)

    plaintext = "CIN: AB123456"
    ciphertext = await kms.encrypt(plaintext, "test-tenant")

    # Verify it's valid base64
    raw = base64.b64decode(ciphertext)
    assert len(raw) > 12 + 16  # nonce + tag minimum

    # Decrypt
    decrypted = await kms.decrypt(ciphertext, "test-tenant")
    assert decrypted == plaintext


@pytest.mark.asyncio
async def test_decrypt_tampered_ciphertext_raises():
    """Tampered ciphertext raises CRIDecryptionError."""
    from app.core.exceptions import CRIDecryptionError
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    data_key = secrets.token_bytes(32)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=data_key.hex())
    mock_factory = MagicMock()

    kms = KMSService(mock_factory, mock_redis, master_hex)

    # Encrypt, then tamper
    ciphertext = await kms.encrypt("secret data", "test-tenant")
    raw = bytearray(base64.b64decode(ciphertext))
    raw[-1] ^= 0xFF  # Flip last byte (in GCM tag region)
    tampered_b64 = base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(CRIDecryptionError):
        await kms.decrypt(tampered_b64, "test-tenant")


@pytest.mark.asyncio
async def test_decrypt_too_short_ciphertext_raises():
    """Ciphertext shorter than nonce + tag minimum raises CRIDecryptionError."""
    from app.core.exceptions import CRIDecryptionError
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)
    data_key = secrets.token_bytes(32)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=data_key.hex())
    mock_factory = MagicMock()

    kms = KMSService(mock_factory, mock_redis, master_hex)
    short_b64 = base64.b64encode(b"tooshort").decode("ascii")

    with pytest.raises(CRIDecryptionError, match="too short"):
        await kms.decrypt(short_b64, "test-tenant")


@pytest.mark.asyncio
async def test_get_data_key_no_active_key_raises():
    """No active key in DB → CRIDecryptionError."""
    from app.core.exceptions import CRIDecryptionError
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_factory = MagicMock(return_value=mock_session)

    kms = KMSService(mock_factory, mock_redis, master_hex)

    with pytest.raises(CRIDecryptionError, match="No active encryption key"):
        await kms._get_data_key("nonexistent-tenant")


@pytest.mark.asyncio
async def test_rotate_key():
    """rotate_key deactivates old key, creates new, invalidates cache."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    # Mock session: scalar_one_or_none returns current version
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = 1
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_factory = MagicMock(return_value=mock_session)

    kms = KMSService(mock_factory, mock_redis, master_hex)
    tenant_id = uuid.uuid4()

    await kms.rotate_key(tenant_id, "test-tenant")

    # Cache invalidated
    mock_redis.delete.assert_called_once_with("test-tenant:kms:data_key")
    # DB: execute called for SELECT version, UPDATE deactivate, then add + commit
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert added_obj.key_version == 2
    assert added_obj.is_active is True
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_tenant_key():
    """delete_tenant_key removes all keys and invalidates cache."""
    from app.services.crypto.kms import KMSService

    master_hex = secrets.token_hex(32)

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)

    kms = KMSService(mock_factory, mock_redis, master_hex)
    tenant_id = uuid.uuid4()

    await kms.delete_tenant_key(tenant_id, "test-tenant")

    mock_redis.delete.assert_called_once_with("test-tenant:kms:data_key")
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
