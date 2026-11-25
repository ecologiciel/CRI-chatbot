"""Transactional rewrapping of existing tenant data keys.

The caller must stop all application writers before invoking this function and
coordinate the master-key configuration change with the committed transaction.
This module does not modify configuration, rotate data keys, re-encrypt data,
or provide crash recovery across the database and configuration file.
"""

from __future__ import annotations

import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.tenant_key import TenantKey

_NONCE_SIZE = 12
_DATA_KEY_SIZE = 32
_TAG_SIZE = 16


def rewrap_key_blobs(blobs: list[bytes], old_master: bytes, new_master: bytes) -> list[bytes]:
    """Authenticate every existing key before returning replacement envelopes."""
    if len(old_master) != 32 or len(new_master) != 32:
        raise ValueError("Both master keys must be 32 bytes")
    if hmac.compare_digest(old_master, new_master):
        raise ValueError("New master key must differ from the existing key")
    if not blobs:
        raise ValueError("No tenant keys found; refusing an ambiguous rotation")

    old_cipher = AESGCM(old_master)
    new_cipher = AESGCM(new_master)
    data_keys = []
    for value in blobs:
        blob = bytes(value)
        if len(blob) != _NONCE_SIZE + _DATA_KEY_SIZE + _TAG_SIZE:
            raise ValueError("A tenant key envelope has an invalid length")
        try:
            data_key = old_cipher.decrypt(blob[:_NONCE_SIZE], blob[_NONCE_SIZE:], None)
        except InvalidTag:
            raise ValueError(
                "A tenant key could not be authenticated with the old master"
            ) from None
        if len(data_key) != _DATA_KEY_SIZE:
            raise ValueError("A tenant data key has an invalid length")
        data_keys.append(data_key)

    replacements = []
    for data_key in data_keys:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        replacements.append(nonce + new_cipher.encrypt(nonce, data_key, None))
    return replacements


async def rewrap_tenant_keys(
    session_factory: async_sessionmaker[AsyncSession], old_master: bytes, new_master: bytes
) -> int:
    """Rewrap every active and inactive key atomically in PostgreSQL.

    Writers must be offline for the entire configuration switch. All envelopes
    are authenticated before any ORM value is changed, and a transaction locks
    the key table until commit. Exceptions roll back the database transaction.
    """
    async with session_factory() as session, session.begin():
        await session.execute(text("LOCK TABLE public.tenant_keys IN ACCESS EXCLUSIVE MODE"))
        rows = list((await session.execute(select(TenantKey).order_by(TenantKey.id))).scalars())
        if any(row.algorithm != "AES-256-GCM" for row in rows):
            raise ValueError("Unsupported tenant key algorithm")
        replacements = rewrap_key_blobs([row.encrypted_key for row in rows], old_master, new_master)
        for row, replacement in zip(rows, replacements, strict=True):
            row.encrypted_key = replacement
        await session.flush()
        return len(rows)
