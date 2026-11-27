"""Version-bound encryption for future tenant-scoped durable records.

Unlike the legacy KMS helpers, decryption selects the historical key version.
This module does not create, rotate or delete keys and does not use Redis.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from app.core.exceptions import CRIDecryptionError, CRIEncryptionError
from app.models.tenant_key import TenantKey

_PURPOSE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_NONCE_SIZE = 12


@dataclass(frozen=True, slots=True)
class VersionedEnvelope:
    version: int
    ciphertext: str


class VersionedEnvelopeService:
    """Use a tenant key version and bind ciphertext to its intended record."""

    def __init__(self, session_factory, master_key_hex: str) -> None:
        key = bytes.fromhex(master_key_hex)
        if len(key) != 32:
            raise ValueError("Master key must be 32 bytes")
        self._master = AESGCM(key)
        self._session_factory = session_factory

    @staticmethod
    def _aad(tenant_id: uuid.UUID, purpose: str, record_id: uuid.UUID, version: int) -> bytes:
        if not _PURPOSE.fullmatch(purpose) or version < 1:
            raise ValueError("Invalid envelope context")
        return f"cri-envelope-v1:{tenant_id}:{purpose}:{record_id}:{version}".encode("ascii")

    async def _key(self, tenant_id: uuid.UUID, version: int | None) -> tuple[int, bytes]:
        statement = select(TenantKey.key_version, TenantKey.encrypted_key).where(
            TenantKey.tenant_id == tenant_id
        )
        if version is None:
            statement = statement.where(TenantKey.is_active.is_(True))
        else:
            statement = statement.where(TenantKey.key_version == version)
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            raise CRIDecryptionError("Tenant encryption key unavailable")
        try:
            blob = bytes(row.encrypted_key)
            key = self._master.decrypt(blob[:_NONCE_SIZE], blob[_NONCE_SIZE:], None)
            if len(key) != 32:
                raise ValueError("Invalid data key size")
            return int(row.key_version), key
        except (InvalidTag, ValueError, TypeError) as exc:
            raise CRIDecryptionError("Tenant encryption key unavailable") from exc

    async def encrypt(
        self, plaintext: bytes, *, tenant_id: uuid.UUID, purpose: str, record_id: uuid.UUID
    ) -> VersionedEnvelope:
        version, key = await self._key(tenant_id, None)
        try:
            aad = self._aad(tenant_id, purpose, record_id, version)
            nonce = secrets.token_bytes(_NONCE_SIZE)
            encrypted = AESGCM(key).encrypt(nonce, plaintext, aad)
            return VersionedEnvelope(version, base64.b64encode(nonce + encrypted).decode("ascii"))
        except (TypeError, ValueError) as exc:
            raise CRIEncryptionError("Unable to encrypt tenant record") from exc

    async def whatsapp_sender_fingerprint(
        self, *, tenant_id: uuid.UUID, channel_id: str, sender_id: str
    ) -> str:
        """Return a stable, tenant-bound opaque conversation key.

        Version 1 of the tenant data key is deliberately retained across data
        key rotations; missing historical key material is a hard failure.
        """
        if not channel_id or len(channel_id) > 32 or not sender_id or len(sender_id) > 128:
            raise ValueError("Invalid WhatsApp conversation identifier")
        _, data_key = await self._key(tenant_id, 1)
        purpose_key = hmac.new(data_key, b"cri-wa-conversation-key-v1", hashlib.sha256).digest()
        context = json.dumps(
            [str(tenant_id), channel_id, sender_id], ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
        return hmac.new(purpose_key, context, hashlib.sha256).hexdigest()

    async def decrypt(
        self,
        envelope: VersionedEnvelope,
        *,
        tenant_id: uuid.UUID,
        purpose: str,
        record_id: uuid.UUID,
    ) -> bytes:
        try:
            aad = self._aad(tenant_id, purpose, record_id, envelope.version)
            raw = base64.b64decode(envelope.ciphertext, validate=True)
            if len(raw) < _NONCE_SIZE + 16:
                raise ValueError("Invalid envelope")
            _, key = await self._key(tenant_id, envelope.version)
            return AESGCM(key).decrypt(raw[:_NONCE_SIZE], raw[_NONCE_SIZE:], aad)
        except (InvalidTag, ValueError, TypeError, binascii.Error) as exc:
            raise CRIDecryptionError("Unable to decrypt tenant record") from exc
