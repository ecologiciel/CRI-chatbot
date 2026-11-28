"""Staged encrypted tracking state, bound to an institution and a phone.

The public tracking route remains disabled until delivery, retention and the
complete authentication flow have been verified.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import re
import uuid

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.orchestrator.tracking_state import (
    TRACKING_STATE_TTL,
    TrackingStateManager,
    TrackingStep,
    TrackingUserState,
)

_PHONE = re.compile(r"\+[1-9][0-9]{6,14}\Z", re.ASCII)
_MAX_PAYLOAD = 65536
_FIELDS = {"step", "identifier", "identifier_type", "otp_attempts", "session_token", "dossier_ids"}


class SecureTrackingStateError(RuntimeError):
    """The encrypted state is unavailable or invalid; do not continue."""


class SecureTrackingStateManager(TrackingStateManager):
    """Encrypt per-phone state with the institution's versioned data key."""

    @staticmethod
    def _key_and_record(tenant, phone):
        if not isinstance(phone, str) or not _PHONE.fullmatch(phone):
            raise SecureTrackingStateError("Invalid tracking context")
        try:
            master = bytes.fromhex(get_settings().kms_master_key)
        except (TypeError, ValueError) as exc:
            raise SecureTrackingStateError("Tracking key unavailable") from exc
        if len(master) != 32:
            raise SecureTrackingStateError("Tracking key unavailable")
        context = tenant.id.bytes + b"\0" + phone.encode("ascii")
        fingerprint = hmac.new(
            master, b"tracking-redis-key-v1\0" + context, hashlib.sha256
        ).hexdigest()
        record_id = uuid.uuid5(tenant.id, "tracking-state-v1:" + phone)
        return f"{tenant.slug}:tracking_state_v2:{fingerprint}", record_id

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
        raw = await get_redis().get(key)
        if raw is None:
            return TrackingUserState()
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
            return self._validate(json.loads(plain))
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
            await get_redis().set(key, serialized, ex=TRACKING_STATE_TTL)
        except Exception as exc:
            raise SecureTrackingStateError("Tracking state unavailable") from exc

    async def clear_state(self, phone, tenant):
        key, _ = self._key_and_record(tenant, phone)
        await get_redis().delete(key)
