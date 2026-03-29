"""KMS (Key Management Service) — per-tenant envelope encryption.

Implements a two-layer key hierarchy:
  Master Key (env var KMS_MASTER_KEY) → wraps Data Keys (per tenant)
  Data Key (per tenant) → encrypts actual sensitive data (CIN, dossiers)

Algorithm: AES-256-GCM (authenticated encryption with associated data).
Nonce: 12 bytes (96 bits), random per operation, stored as ciphertext prefix.

SECURITY INVARIANTS:
  - Master key and decrypted data keys are NEVER logged.
  - Data keys are cached in Redis for 5 min (hex-encoded, not raw bytes).
  - Each tenant has exactly one active key (enforced by partial unique index).
"""

from __future__ import annotations

import base64
import secrets
import uuid
from datetime import datetime, timezone

import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import CRIDecryptionError, CRIEncryptionError
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey

logger = structlog.get_logger()


class KMSService:
    """Per-tenant envelope encryption using AES-256-GCM.

    Args:
        session_factory: Async SQLAlchemy session factory (public schema).
        redis_client: Async Redis client (decode_responses=True).
        master_key_hex: Hex-encoded 32-byte master key from env.
    """

    NONCE_SIZE = 12  # 96 bits, recommended for AES-GCM
    CACHE_TTL = 300  # 5 minutes

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: object,
        master_key_hex: str,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._master_key = bytes.fromhex(master_key_hex)
        if len(self._master_key) != 32:
            msg = "Master key must be 32 bytes (256 bits)"
            raise ValueError(msg)
        self._master_aesgcm = AESGCM(self._master_key)
        self._log = logger.bind(service="kms")

    # ── Key lifecycle ──

    async def generate_tenant_key(self, tenant_id: uuid.UUID) -> None:
        """Generate and store a new AES-256 data key for a tenant.

        Called during tenant provisioning. The data key is encrypted by the
        master key before storage (envelope encryption).

        Args:
            tenant_id: UUID of the tenant to generate a key for.
        """
        # 1. Generate random 32-byte data key
        data_key = secrets.token_bytes(32)

        # 2. Encrypt with master key
        nonce = secrets.token_bytes(self.NONCE_SIZE)
        encrypted = self._master_aesgcm.encrypt(nonce, data_key, None)

        # 3. Store: nonce (12B) + ciphertext + tag (16B)
        stored_blob = nonce + encrypted

        async with self._session_factory() as session:
            tenant_key = TenantKey(
                tenant_id=tenant_id,
                encrypted_key=stored_blob,
                algorithm="AES-256-GCM",
                key_version=1,
                is_active=True,
            )
            session.add(tenant_key)
            await session.commit()

        self._log.info(
            "tenant_key_generated",
            tenant_id=str(tenant_id),
        )

    async def rotate_key(
        self, tenant_id: uuid.UUID, tenant_slug: str
    ) -> None:
        """Rotate the encryption key for a tenant.

        Deactivates the current key and generates a new one with an
        incremented version number. Existing data encrypted with the old
        key must be re-encrypted separately (out of scope).

        Args:
            tenant_id: UUID of the tenant.
            tenant_slug: Slug for Redis cache invalidation.
        """
        # 1. Invalidate cache
        cache_key = f"{tenant_slug}:kms:data_key"
        await self._redis.delete(cache_key)

        async with self._session_factory() as session:
            # 2. Get current version
            result = await session.execute(
                select(TenantKey.key_version)
                .where(TenantKey.tenant_id == tenant_id)
                .where(TenantKey.is_active.is_(True))
            )
            current_version = result.scalar_one_or_none() or 0

            # 3. Deactivate old key
            await session.execute(
                update(TenantKey)
                .where(TenantKey.tenant_id == tenant_id)
                .where(TenantKey.is_active.is_(True))
                .values(
                    is_active=False,
                    rotated_at=datetime.now(timezone.utc),
                )
            )

            # 4. Generate new data key
            data_key = secrets.token_bytes(32)
            nonce = secrets.token_bytes(self.NONCE_SIZE)
            encrypted = self._master_aesgcm.encrypt(nonce, data_key, None)
            stored_blob = nonce + encrypted

            new_key = TenantKey(
                tenant_id=tenant_id,
                encrypted_key=stored_blob,
                algorithm="AES-256-GCM",
                key_version=current_version + 1,
                is_active=True,
            )
            session.add(new_key)
            await session.commit()

        self._log.info(
            "tenant_key_rotated",
            tenant_id=str(tenant_id),
            new_version=current_version + 1,
        )

    async def delete_tenant_key(
        self, tenant_id: uuid.UUID, tenant_slug: str
    ) -> None:
        """Delete all keys for a tenant (provisioning rollback / deprovision).

        Args:
            tenant_id: UUID of the tenant.
            tenant_slug: Slug for Redis cache invalidation.
        """
        # Invalidate cache
        cache_key = f"{tenant_slug}:kms:data_key"
        await self._redis.delete(cache_key)

        async with self._session_factory() as session:
            from sqlalchemy import delete

            await session.execute(
                delete(TenantKey).where(TenantKey.tenant_id == tenant_id)
            )
            await session.commit()

        self._log.info(
            "tenant_key_deleted",
            tenant_id=str(tenant_id),
        )

    # ── Encrypt / Decrypt ──

    async def encrypt(self, plaintext: str, tenant_slug: str) -> str:
        """Encrypt a plaintext string with the tenant's data key.

        Args:
            plaintext: Text to encrypt.
            tenant_slug: Identifies which tenant's key to use.

        Returns:
            Base64-encoded string: nonce (12B) + ciphertext + tag (16B).

        Raises:
            CRIEncryptionError: If encryption fails.
        """
        try:
            data_key = await self._get_data_key(tenant_slug)
            aesgcm = AESGCM(data_key)
            nonce = secrets.token_bytes(self.NONCE_SIZE)
            ciphertext = aesgcm.encrypt(
                nonce, plaintext.encode("utf-8"), None
            )
            return base64.b64encode(nonce + ciphertext).decode("ascii")
        except CRIDecryptionError:
            raise
        except Exception as exc:
            raise CRIEncryptionError(
                f"Encryption failed for tenant {tenant_slug}"
            ) from exc

    async def decrypt(self, ciphertext_b64: str, tenant_slug: str) -> str:
        """Decrypt a base64-encoded ciphertext with the tenant's data key.

        Args:
            ciphertext_b64: Base64-encoded ciphertext (nonce + ct + tag).
            tenant_slug: Identifies which tenant's key to use.

        Returns:
            Decrypted plaintext string.

        Raises:
            CRIDecryptionError: If decryption fails (bad key, tampered data).
        """
        try:
            data_key = await self._get_data_key(tenant_slug)
            raw = base64.b64decode(ciphertext_b64)

            if len(raw) < self.NONCE_SIZE + 16:
                raise CRIDecryptionError("Ciphertext too short")

            nonce = raw[: self.NONCE_SIZE]
            ciphertext = raw[self.NONCE_SIZE :]

            aesgcm = AESGCM(data_key)
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext_bytes.decode("utf-8")
        except CRIDecryptionError:
            raise
        except InvalidTag:
            raise CRIDecryptionError(
                f"Decryption failed for tenant {tenant_slug}: "
                "invalid tag (tampered or wrong key)"
            ) from None
        except Exception as exc:
            raise CRIDecryptionError(
                f"Decryption failed for tenant {tenant_slug}"
            ) from exc

    # ── Internal ──

    async def _get_data_key(self, tenant_slug: str) -> bytes:
        """Retrieve the decrypted data key for a tenant (cached in Redis).

        Resolution path:
          1. Redis cache hit → hex string → bytes
          2. Cache miss → DB JOIN (tenant_keys + tenants) → decrypt → cache

        Args:
            tenant_slug: Tenant slug for cache key and DB lookup.

        Returns:
            Raw 32-byte data key.

        Raises:
            CRIDecryptionError: If no active key found or decryption fails.
        """
        cache_key = f"{tenant_slug}:kms:data_key"

        # 1. Check Redis cache (stored as hex string due to decode_responses=True)
        cached = await self._redis.get(cache_key)
        if cached:
            return bytes.fromhex(cached)

        # 2. Cache miss — query DB
        async with self._session_factory() as session:
            result = await session.execute(
                select(TenantKey.encrypted_key)
                .join(Tenant, TenantKey.tenant_id == Tenant.id)
                .where(Tenant.slug == tenant_slug)
                .where(TenantKey.is_active.is_(True))
            )
            row = result.scalar_one_or_none()

        if row is None:
            raise CRIDecryptionError(
                f"No active encryption key for tenant {tenant_slug}"
            )

        encrypted_blob = bytes(row) if not isinstance(row, bytes) else row

        # 3. Decrypt: extract nonce (12B) + wrapped key
        nonce = encrypted_blob[: self.NONCE_SIZE]
        wrapped_key = encrypted_blob[self.NONCE_SIZE :]

        try:
            data_key = self._master_aesgcm.decrypt(nonce, wrapped_key, None)
        except InvalidTag:
            raise CRIDecryptionError(
                f"Failed to unwrap data key for tenant {tenant_slug}: "
                "master key mismatch or corrupted key"
            ) from None

        # 4. Cache as hex string (Redis decode_responses=True)
        await self._redis.set(cache_key, data_key.hex(), ex=self.CACHE_TTL)

        return data_key
