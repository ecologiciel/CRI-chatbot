"""Shared transaction lock for acceptance and claiming of one conversation."""

import re
import uuid

from sqlalchemy import text

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def lock_key(tenant_id: uuid.UUID, fingerprint: str) -> str:
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("Invalid conversation fingerprint")
    return f"wa-inbox-conversation:{tenant_id}:{fingerprint}"


async def lock_for_acceptance(session, tenant_id: uuid.UUID, fingerprint: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": lock_key(tenant_id, fingerprint)},
    )


async def try_lock_for_claim(session, tenant_id: uuid.UUID, fingerprint: str) -> bool:
    return bool(
        (await session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key(tenant_id, fingerprint)},
        )).scalar_one()
    )
