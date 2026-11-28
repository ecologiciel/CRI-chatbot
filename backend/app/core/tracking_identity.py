"""Opaque Redis identity for staged tracking operations."""

from __future__ import annotations

import hashlib
import hmac
import re

_PHONE = re.compile(r"\+[1-9][0-9]{6,14}\Z", re.ASCII)


def subject_fingerprint(tenant, phone, master_hex):
    """Bind a pseudonymous subject to an immutable institution and phone."""
    if not isinstance(phone, str) or not _PHONE.fullmatch(phone):
        raise ValueError("Invalid tracking context")
    try:
        master = bytes.fromhex(master_hex)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tracking key unavailable") from exc
    if len(master) != 32:
        raise ValueError("Tracking key unavailable")
    context = tenant.id.bytes + b"\0" + phone.encode("ascii")
    return hmac.new(master, b"tracking-subject-v1\0" + context, hashlib.sha256).hexdigest()


def subject_key(tenant, phone, kind, master_hex):
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,48}", kind, re.ASCII):
        raise ValueError("Invalid tracking key type")
    fingerprint = subject_fingerprint(tenant, phone, master_hex)
    # The shared hash tag keeps all state/OTP keys for one subject in the
    # same Redis Cluster slot; raw phone numbers are absent from keys.
    return f"{tenant.slug}:tracking_v2:{{{fingerprint}}}:{kind}"
