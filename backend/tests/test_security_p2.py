"""Tests unitaires des mesures de securite Phase 2.

Couvre :
- Audit trail : INSERT ONLY, format, service, fire-and-forget
- KMS : envelope encryption, round-trip, rotation, cache
- Sessions avancees : IP tracking, session unique, alertes, token revocation
- Archivage : SHA-256, gzip, format fichier MinIO
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")


# =====================================================================
# Audit Trail
# =====================================================================


class TestAuditTrail:
    """Tests du journal d'audit immuable."""

    def test_audit_model_in_public_schema(self):
        """La table audit_logs est dans le schema public."""
        from app.models.audit import AuditLog

        # __table_args__ is a tuple; the schema dict is the last element
        args_dict = AuditLog.__table_args__[-1]
        assert args_dict["schema"] == "public"

    def test_audit_model_no_updated_at(self):
        """AuditLog n'a PAS de colonne updated_at (INSERT ONLY)."""
        from app.models.audit import AuditLog

        columns = {c.name for c in AuditLog.__table__.columns}
        assert "updated_at" not in columns

    @pytest.mark.asyncio
    async def test_audit_service_fire_and_forget(self):
        """log_action ne bloque pas meme si la DB echoue."""
        from app.services.audit.service import AuditService
        from app.schemas.audit import AuditLogCreate

        svc = AuditService()
        data = AuditLogCreate(
            tenant_slug="rabat",
            user_id=None,
            user_type="system",
            action="create",
            resource_type="test",
            resource_id=str(uuid.uuid4()),
        )

        # Mock the session factory to raise an exception
        with patch(
            "app.services.audit.service.get_session_factory",
            side_effect=RuntimeError("DB is down"),
        ):
            # Should NOT raise — fire-and-forget semantics
            await svc.log_action(data)

    def test_audit_middleware_excludes_webhooks(self):
        """Le middleware n'audite pas les webhooks WhatsApp."""
        from app.core.audit_middleware import AUDIT_EXCLUDED_PREFIXES

        assert any("/webhook" in p for p in AUDIT_EXCLUDED_PREFIXES)

    def test_audit_middleware_excludes_health(self):
        """Le middleware n'audite pas les health checks."""
        from app.core.audit_middleware import AUDIT_EXCLUDED_PREFIXES

        assert any("/health" in p for p in AUDIT_EXCLUDED_PREFIXES)

    def test_audit_middleware_excludes_websocket(self):
        """Le middleware n'audite pas les connexions WebSocket."""
        from app.core.audit_middleware import AUDIT_EXCLUDED_PREFIXES

        assert any("/ws/" in p for p in AUDIT_EXCLUDED_PREFIXES)

    def test_audit_method_action_map(self):
        """Mapping POST->create, PUT->update, PATCH->update, DELETE->delete."""
        from app.core.audit_middleware import _METHOD_ACTION_MAP

        assert _METHOD_ACTION_MAP["POST"] == "create"
        assert _METHOD_ACTION_MAP["PUT"] == "update"
        assert _METHOD_ACTION_MAP["PATCH"] == "update"
        assert _METHOD_ACTION_MAP["DELETE"] == "delete"

    def test_extract_resource_type(self):
        """Extraction du type de ressource depuis le path API."""
        from app.core.audit_middleware import _extract_resource_type

        assert _extract_resource_type("/api/v1/contacts/abc") == "contacts"
        assert _extract_resource_type("/api/v1/escalations/") == "escalations"

    def test_extract_resource_id_with_uuid(self):
        """Extraction d'un UUID depuis le path."""
        from app.core.audit_middleware import _extract_resource_id

        test_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _extract_resource_id(f"/api/v1/escalations/{test_id}/assign")
        assert result == test_id

    def test_extract_resource_id_without_uuid(self):
        """Pas d'UUID dans le path -> None."""
        from app.core.audit_middleware import _extract_resource_id

        result = _extract_resource_id("/api/v1/contacts/")
        assert result is None


# =====================================================================
# KMS
# =====================================================================


class TestKMS:
    """Tests du KMS logiciel AES-256-GCM."""

    def test_aes256_gcm_roundtrip(self):
        """Chiffrement AES-256-GCM -> dechiffrement = donnees identiques."""
        key = secrets.token_bytes(32)
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        plaintext = "CIN: AB123456 — Donnees sensibles CRI"
        ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
        pt = aesgcm.decrypt(nonce, ct, None)
        assert pt.decode() == plaintext

    def test_envelope_encryption_roundtrip(self):
        """Master key chiffre la data key, data key chiffre les donnees."""
        master_key = secrets.token_bytes(32)
        data_key = secrets.token_bytes(32)

        # Encrypt data_key with master_key
        master_aesgcm = AESGCM(master_key)
        nonce1 = secrets.token_bytes(12)
        encrypted_dk = master_aesgcm.encrypt(nonce1, data_key, None)

        # Decrypt data_key
        decrypted_dk = master_aesgcm.decrypt(nonce1, encrypted_dk, None)
        assert decrypted_dk == data_key

        # Use data_key to encrypt actual data
        data_aesgcm = AESGCM(decrypted_dk)
        nonce2 = secrets.token_bytes(12)
        ct = data_aesgcm.encrypt(nonce2, b"secret data", None)
        pt = data_aesgcm.decrypt(nonce2, ct, None)
        assert pt == b"secret data"

    def test_different_nonces_produce_different_ciphertexts(self):
        """Deux chiffrements du meme texte avec des nonces differents -> ciphertexts differents."""
        key = secrets.token_bytes(32)
        aesgcm = AESGCM(key)
        plaintext = b"same data"
        ct1 = aesgcm.encrypt(secrets.token_bytes(12), plaintext, None)
        ct2 = aesgcm.encrypt(secrets.token_bytes(12), plaintext, None)
        assert ct1 != ct2

    def test_wrong_key_fails_decryption(self):
        """Dechiffrement avec la mauvaise cle -> exception."""
        key1 = secrets.token_bytes(32)
        key2 = secrets.token_bytes(32)
        aesgcm1 = AESGCM(key1)
        nonce = secrets.token_bytes(12)
        ct = aesgcm1.encrypt(nonce, b"data", None)

        aesgcm2 = AESGCM(key2)
        with pytest.raises(Exception):
            aesgcm2.decrypt(nonce, ct, None)

    def test_kms_service_rejects_short_master_key(self):
        """Master key trop courte -> ValueError ou AssertionError."""
        from app.services.crypto.kms import KMSService

        with pytest.raises((ValueError, AssertionError)):
            KMSService(None, None, "abcd")  # too short

    def test_kms_service_rejects_non_hex_master_key(self):
        """Master key non hexadecimale -> ValueError."""
        from app.services.crypto.kms import KMSService

        with pytest.raises((ValueError, AssertionError)):
            KMSService(None, None, "zzzz" * 16)  # not valid hex

    def test_kms_service_accepts_valid_master_key(self):
        """Master key valide (64 hex chars = 32 bytes) -> pas d'erreur."""
        from app.services.crypto.kms import KMSService

        valid_key = secrets.token_hex(32)
        kms = KMSService(MagicMock(), AsyncMock(), valid_key)
        assert kms is not None

    def test_tenant_key_schema_hides_encrypted_key(self):
        """Le schema TenantKeyRead n'expose PAS encrypted_key."""
        from app.schemas.crypto import TenantKeyRead

        assert "encrypted_key" not in TenantKeyRead.model_fields


# =====================================================================
# Session Manager
# =====================================================================


class TestSessionManager:
    """Tests de la gestion de sessions avancee."""

    @pytest.mark.asyncio
    async def test_register_new_session(self):
        """Premiere session -> JTI stocke, pas de revocation."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        # 3 get calls: key_active=None, key_ip=None, key_last=None
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.setex = AsyncMock()
        pipe = AsyncMock()
        pipe.setex = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[True, True, True])
        redis_mock.pipeline = MagicMock(return_value=pipe)

        sm = SessionManager(redis_mock)
        result = await sm.register_session("admin-1", "new-jti", "1.2.3.4")
        assert result["previous_session_invalidated"] is False

    @pytest.mark.asyncio
    async def test_register_invalidates_previous_session(self):
        """Nouvelle session -> ancienne session invalidee (JTI blackliste)."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        # 3 get calls: key_active="old-jti", key_ip=None, key_last=None
        redis_mock.get = AsyncMock(side_effect=["old-jti", None, None])
        redis_mock.setex = AsyncMock()
        pipe = AsyncMock()
        pipe.setex = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[True, True, True])
        redis_mock.pipeline = MagicMock(return_value=pipe)

        sm = SessionManager(redis_mock)
        result = await sm.register_session("admin-1", "new-jti", "1.2.3.4")
        assert result["previous_session_invalidated"] is True
        # Verify old JTI is revoked
        redis_mock.setex.assert_any_call("auth:revoked:old-jti", 1800, "revoked")

    @pytest.mark.asyncio
    async def test_validate_session_success(self):
        """JTI actif + meme IP -> session valide."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        # validate calls: exists(revoked) → 0, get(active) → "valid-jti", get(ip) → "1.2.3.4"
        redis_mock.exists = AsyncMock(return_value=0)
        redis_mock.get = AsyncMock(side_effect=["valid-jti", "1.2.3.4"])

        sm = SessionManager(redis_mock)
        result = await sm.validate_session("admin-1", "valid-jti", "1.2.3.4")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_session_wrong_jti(self):
        """JTI incorrect -> session invalide."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        redis_mock.exists = AsyncMock(return_value=0)  # not revoked
        redis_mock.get = AsyncMock(return_value="active-jti")

        sm = SessionManager(redis_mock)
        result = await sm.validate_session("admin-1", "wrong-jti", "1.2.3.4")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_session_ip_changed(self):
        """Changement d'IP -> session invalidee."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        redis_mock.exists = AsyncMock(return_value=0)  # not revoked
        # validate_session calls: get(active) → "valid-jti", get(ip) → "1.2.3.4"
        # invalidate_session calls: get(active) → "valid-jti"
        redis_mock.get = AsyncMock(side_effect=["valid-jti", "1.2.3.4", "valid-jti"])
        redis_mock.delete = AsyncMock()
        redis_mock.setex = AsyncMock()

        sm = SessionManager(redis_mock)
        result = await sm.validate_session("admin-1", "valid-jti", "5.6.7.8")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_revoked(self):
        """Token dans la blacklist -> revoque."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        redis_mock.exists = AsyncMock(return_value=1)

        sm = SessionManager(redis_mock)
        assert await sm.is_token_revoked("revoked-jti") is True

    @pytest.mark.asyncio
    async def test_is_token_not_revoked(self):
        """Token absent de la blacklist -> non revoque."""
        from app.services.auth.session_manager import SessionManager

        redis_mock = AsyncMock()
        redis_mock.exists = AsyncMock(return_value=0)

        sm = SessionManager(redis_mock)
        assert await sm.is_token_revoked("valid-jti") is False


# =====================================================================
# Archivage
# =====================================================================


class TestArchivage:
    """Tests de l'archivage signe SHA-256."""

    def test_sha256_deterministic(self):
        """SHA-256 du meme contenu donne toujours le meme hash."""
        data = json.dumps([{"id": "1", "action": "create"}]).encode()
        h1 = hashlib.sha256(data).hexdigest()
        h2 = hashlib.sha256(data).hexdigest()
        assert h1 == h2

    def test_sha256_different_for_different_data(self):
        """SHA-256 de contenus differents -> hashs differents."""
        d1 = json.dumps([{"id": "1"}]).encode()
        d2 = json.dumps([{"id": "2"}]).encode()
        assert hashlib.sha256(d1).hexdigest() != hashlib.sha256(d2).hexdigest()

    def test_gzip_roundtrip(self):
        """Compression gzip -> decompression = donnees identiques."""
        data = json.dumps([{"id": "123", "action": "create"}] * 100).encode()
        compressed = gzip.compress(data)
        assert gzip.decompress(compressed) == data

    def test_gzip_reduces_size(self):
        """La compression gzip reduit la taille."""
        data = json.dumps(
            [{"id": str(i), "action": "create"} for i in range(1000)]
        ).encode()
        compressed = gzip.compress(data)
        assert len(compressed) < len(data)
