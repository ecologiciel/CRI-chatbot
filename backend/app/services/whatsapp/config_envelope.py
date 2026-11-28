"""Staged authenticated envelope for per-tenant WhatsApp configuration.

Only the provider's phone-number ID stays in clear for indexed webhook
routing. This helper is not yet wired into reads, writes or migrations.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CRIDecryptionError, CRIEncryptionError
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService

_FORMAT = "wa-config-envelope-v1"
_PURPOSE = "wa_channel_config"
_MAX_BYTES = 131_072
_RESERVED = frozenset({"_envelope", "_format"})


def is_sealed_or_malformed(config: dict[str, Any]) -> bool:
    """Do not interpret a damaged envelope as a legacy plaintext config."""
    return bool(_RESERVED.intersection(config))


async def load_channel_config(
    tenant_id: uuid.UUID,
    stored: dict[str, Any] | None,
    cipher: VersionedEnvelopeService | None,
    *,
    require_encryption: bool = False,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Read an envelope or, during a controlled transition, legacy plaintext."""
    if stored is None:
        return None
    if not isinstance(stored, dict):
        raise CRIDecryptionError("Invalid channel configuration")
    if is_sealed_or_malformed(stored):
        if cipher is None:
            raise CRIDecryptionError("Channel encryption key unavailable")
        return await open_channel_config(tenant_id, stored, cipher, session=session)
    if require_encryption:
        raise CRIDecryptionError("Plaintext channel configuration is disabled")
    return dict(stored)


async def prepare_channel_config_write(
    tenant_id: uuid.UUID,
    config: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    cipher: VersionedEnvelopeService | None,
    *,
    require_encryption: bool = False,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Never downgrade a sealed channel to plaintext during an update."""
    if config is None:
        return None
    if not isinstance(config, dict) or is_sealed_or_malformed(config):
        raise CRIEncryptionError("Invalid channel configuration")
    previous_sealed = isinstance(previous, dict) and is_sealed_or_malformed(previous)
    if previous_sealed or require_encryption:
        if cipher is None:
            raise CRIEncryptionError("Channel encryption key unavailable")
        return await seal_channel_config(tenant_id, config, cipher, session=session)
    return dict(config)


def _valid_channel_id(value: object) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < len(value) <= 32


def _valid_json_keys(value: object, depth: int = 0) -> bool:
    if depth > 50:
        return False
    if isinstance(value, dict):
        return all(isinstance(key, str) and _valid_json_keys(item, depth + 1) for key, item in value.items())
    if isinstance(value, list):
        return all(_valid_json_keys(item, depth + 1) for item in value)
    return True


async def seal_channel_config(
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    cipher: VersionedEnvelopeService,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Encrypt all configuration except the indexed channel identifier."""
    if not isinstance(config, dict) or _RESERVED.intersection(config) or not _valid_json_keys(config):
        raise CRIEncryptionError("Invalid channel configuration")
    channel_id = config.get("phone_number_id")
    if not _valid_channel_id(channel_id):
        raise CRIEncryptionError("Invalid channel configuration")
    private = {key: value for key, value in config.items() if key != "phone_number_id"}
    try:
        plaintext = json.dumps(
            {"phone_number_id": channel_id, "private": private},
            ensure_ascii=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CRIEncryptionError("Invalid channel configuration") from exc
    if len(plaintext) > _MAX_BYTES:
        raise CRIEncryptionError("Channel configuration is too large")
    envelope = await cipher.encrypt(
        plaintext, tenant_id=tenant_id, purpose=_PURPOSE, record_id=tenant_id, session=session,
    )
    return {
        "phone_number_id": channel_id,
        "_format": _FORMAT,
        "_envelope": {"version": envelope.version, "ciphertext": envelope.ciphertext},
    }


async def open_channel_config(
    tenant_id: uuid.UUID,
    stored: dict[str, Any],
    cipher: VersionedEnvelopeService,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Reject plaintext, altered routing IDs, unknown formats and bad envelopes."""
    try:
        if not isinstance(stored, dict) or set(stored) != {"phone_number_id", "_format", "_envelope"}:
            raise ValueError("invalid envelope structure")
        channel_id = stored["phone_number_id"]
        item = stored["_envelope"]
        if (
            not _valid_channel_id(channel_id) or stored["_format"] != _FORMAT
            or not isinstance(item, dict) or set(item) != {"version", "ciphertext"}
            or type(item["version"]) is not int or item["version"] < 1
            or not isinstance(item["ciphertext"], str) or len(item["ciphertext"]) > (_MAX_BYTES * 2)
        ):
            raise ValueError("invalid envelope metadata")
        plaintext = await cipher.decrypt(
            VersionedEnvelope(item["version"], item["ciphertext"]),
            tenant_id=tenant_id, purpose=_PURPOSE, record_id=tenant_id, session=session,
        )
        if len(plaintext) > _MAX_BYTES:
            raise ValueError("oversized envelope")
        payload = json.loads(plaintext)
        if (
            not isinstance(payload, dict) or set(payload) != {"phone_number_id", "private"}
            or payload["phone_number_id"] != channel_id or not isinstance(payload["private"], dict)
            or "phone_number_id" in payload["private"] or _RESERVED.intersection(payload["private"])
        ):
            raise ValueError("channel identity mismatch")
        return {"phone_number_id": channel_id, **payload["private"]}
    except (KeyError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CRIDecryptionError("Unable to decrypt channel configuration") from exc
