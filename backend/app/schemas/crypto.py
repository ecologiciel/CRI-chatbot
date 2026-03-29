"""Pydantic v2 schemas for KMS / Crypto operations.

SECURITY: TenantKeyRead intentionally excludes encrypted_key —
the wrapped data key must NEVER be exposed via any API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantKeyRead(BaseModel):
    """Public representation of a tenant's encryption key metadata.

    Excludes encrypted_key to prevent key material leakage.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    algorithm: str
    key_version: int
    is_active: bool
    created_at: datetime
    rotated_at: datetime | None


class EncryptRequest(BaseModel):
    """Request to encrypt a plaintext value."""

    plaintext: str = Field(..., min_length=1)


class EncryptResponse(BaseModel):
    """Encrypted value — base64-encoded ciphertext."""

    ciphertext: str


class DecryptRequest(BaseModel):
    """Request to decrypt a ciphertext value."""

    ciphertext: str = Field(..., min_length=1)


class DecryptResponse(BaseModel):
    """Decrypted plaintext value."""

    plaintext: str
