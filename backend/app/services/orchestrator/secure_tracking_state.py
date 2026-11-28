"""Staged encrypted tracking state, bound to an institution and a phone.

The public tracking route remains disabled until delivery, retention and the
complete authentication flow have been verified.
"""

from __future__ import annotations

import dataclasses
import json
import re
import secrets
import time
import uuid

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.core.tracking_identity import subject_key
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.orchestrator.tracking_state import (
    TRACKING_STATE_TTL,
    TrackingStateManager,
    TrackingStep,
    TrackingUserState,
)

_MAX_PAYLOAD = 65536
_GUARD_TTL = TRACKING_STATE_TTL + 480
_MAX_OPERATION_SECONDS = 420
_FIELDS = {"step", "identifier", "identifier_type", "otp_attempts", "session_token", "dossier_ids"}

_READ_STATE = """
local value = redis.call('GET', KEYS[1])
local revision = redis.call('GET', KEYS[2])
if not revision then
  if value then return redis.error_reply('tracking guard missing') end
  revision = ARGV[1]
  redis.call('SET', KEYS[2], revision, 'EX', ARGV[2])
else
  if redis.call('TTL', KEYS[2]) < 0 then return redis.error_reply('invalid tracking guard') end
  redis.call('EXPIRE', KEYS[2], ARGV[2])
end
return {revision, value or false}
"""

_CHANGE_STATE = """
local revision = redis.call('GET', KEYS[2])
if not revision or revision ~= ARGV[1] then return 0 end
local current = redis.call('GET', KEYS[1])
if ARGV[2] == '0' then
  if current then return 0 end
elseif not current or current ~= ARGV[3] then
  return 0
end
if ARGV[4] ~= 'set' and ARGV[4] ~= 'delete' then
  return redis.error_reply('invalid tracking operation')
end
-- Redis Lua is atomic but does not roll back prior commands after an error.
-- Advance the guard first so a failed state write invalidates stale readers.
redis.call('SET', KEYS[2], ARGV[7], 'EX', ARGV[8])
if ARGV[4] == 'set' then
  redis.call('SET', KEYS[1], ARGV[5], 'EX', ARGV[6])
else
  redis.call('DEL', KEYS[1])
end
return 1
"""


class SecureTrackingStateError(RuntimeError):
    """The encrypted state is unavailable or invalid; do not continue."""


class SecureTrackingStateConflictError(SecureTrackingStateError):
    """Another operation changed or expired the tracking state."""


class SecureTrackingStateManager(TrackingStateManager):
    """Encrypt per-phone state with the institution's versioned data key."""

    @staticmethod
    def _key_and_record(tenant, phone):
        try:
            key = subject_key(tenant, phone, "state", get_settings().kms_master_key)
        except ValueError as exc:
            raise SecureTrackingStateError("Invalid or unavailable tracking context") from exc
        record_id = uuid.uuid5(tenant.id, "tracking-state-v1:" + phone)
        return key, record_id

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict) or set(data) != _FIELDS:
            raise ValueError("Invalid tracking state")
        step = TrackingStep(data["step"])
        identifier, kind, token, attempts, ids = (
            data[key]
            for key in (
                "identifier",
                "identifier_type",
                "session_token",
                "otp_attempts",
                "dossier_ids",
            )
        )
        if identifier is not None and (not isinstance(identifier, str) or len(identifier) > 128):
            raise ValueError("Invalid tracking state")
        if (
            kind not in (None, "numero", "cin")
            or type(attempts) is not int
            or not 0 <= attempts <= 3
        ):
            raise ValueError("Invalid tracking state")
        if token is not None and (
            not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token, re.ASCII)
        ):
            raise ValueError("Invalid tracking state")
        if (
            not isinstance(ids, list)
            or len(ids) > 1000
            or any(not isinstance(value, str) or len(value) > 64 for value in ids)
        ):
            raise ValueError("Invalid tracking state")
        return TrackingUserState(
            step=step,
            identifier=identifier,
            identifier_type=kind,
            session_token=token,
            otp_attempts=attempts,
            dossier_ids=ids,
        )

    @staticmethod
    def _cipher():
        return VersionedEnvelopeService(get_session_factory(), get_settings().kms_master_key)

    async def get_state(self, phone, tenant):
        key, record_id = self._key_and_record(tenant, phone)
        try:
            revision, raw = await get_redis().eval(
                _READ_STATE, 2, key, key + ":guard", secrets.token_hex(16), _GUARD_TTL
            )
            if isinstance(revision, bytes):
                revision = revision.decode("ascii")
            if isinstance(raw, bytes):
                raw = raw.decode("ascii")
        except Exception as exc:
            raise SecureTrackingStateError("Tracking state unavailable") from exc
        if raw is None:
            state = TrackingUserState()
            state._secure_snapshot = (key, revision, None, time.monotonic())
            return state
        try:
            if len(raw) > _MAX_PAYLOAD * 2:
                raise ValueError("Tracking envelope too large")
            data = json.loads(raw)
            if (
                not isinstance(data, dict)
                or set(data) != {"format", "key_version", "ciphertext"}
                or data["format"] != 1
                or type(data["key_version"]) is not int
                or data["key_version"] < 1
                or not isinstance(data["ciphertext"], str)
            ):
                raise ValueError("Invalid tracking envelope")
            plain = await self._cipher().decrypt(
                VersionedEnvelope(data["key_version"], data["ciphertext"]),
                tenant_id=tenant.id,
                purpose="tracking_state",
                record_id=record_id,
            )
            if len(plain) > _MAX_PAYLOAD:
                raise ValueError("Tracking state too large")
            state = self._validate(json.loads(plain))
            state._secure_snapshot = (key, revision, raw, time.monotonic())
            return state
        except Exception as exc:
            raise SecureTrackingStateError("Tracking state unavailable") from exc

    async def set_state(self, phone, state, tenant):
        key, record_id = self._key_and_record(tenant, phone)
        data = dataclasses.asdict(state)
        data["step"] = state.step.value
        try:
            self._validate(data)
            plain = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            if len(plain) > _MAX_PAYLOAD:
                raise ValueError("Tracking state too large")
            envelope = await self._cipher().encrypt(
                plain,
                tenant_id=tenant.id,
                purpose="tracking_state",
                record_id=record_id,
            )
            serialized = json.dumps(
                {"format": 1, "key_version": envelope.version, "ciphertext": envelope.ciphertext},
                separators=(",", ":"),
            )
            await self._change(key, state, "set", serialized)
        except SecureTrackingStateError:
            raise
        except Exception as exc:
            raise SecureTrackingStateError("Tracking state unavailable") from exc

    @staticmethod
    async def _change(key, state, operation, serialized=""):
        snapshot = getattr(state, "_secure_snapshot", None)
        if not isinstance(snapshot, tuple) or len(snapshot) != 4:
            raise SecureTrackingStateConflictError(
                "Tracking state must be read before modification"
            )
        original_key, revision, previous, read_at = snapshot
        if (
            original_key != key
            or not isinstance(read_at, int | float)
            or time.monotonic() - read_at > _MAX_OPERATION_SECONDS
        ):
            raise SecureTrackingStateConflictError("Tracking state context expired or changed")
        next_revision = secrets.token_hex(16)
        changed = await get_redis().eval(
            _CHANGE_STATE,
            2,
            key,
            key + ":guard",
            revision,
            "0" if previous is None else "1",
            previous or "",
            operation,
            serialized,
            TRACKING_STATE_TTL,
            next_revision,
            _GUARD_TTL,
        )
        if changed != 1:
            raise SecureTrackingStateConflictError("Tracking state changed concurrently")
        state._secure_snapshot = (
            key,
            next_revision,
            serialized if operation == "set" else None,
            time.monotonic(),
        )

    async def clear_state(self, phone, tenant, *, expected_state=None):
        key, _ = self._key_and_record(tenant, phone)
        await self._change(key, expected_state, "delete")
