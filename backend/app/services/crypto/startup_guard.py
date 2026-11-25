"""Fail closed if the configured master cannot authenticate stored tenant keys."""

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.tenant_key import TenantKey


def validate_envelopes(master_key: bytes, rows: list[tuple[bytes, str]]) -> None:
    """Validate active and historical keys; an empty database is valid at bootstrap."""
    if len(master_key) != 32:
        raise RuntimeError("Invalid KMS master key configuration")
    cipher = AESGCM(master_key)
    for value, algorithm in rows:
        blob = bytes(value)
        if algorithm != "AES-256-GCM" or len(blob) != 60:
            raise RuntimeError("Tenant key validation failed; check KMS recovery state")
        try:
            cipher.decrypt(blob[:12], blob[12:], None)
        except InvalidTag:
            raise RuntimeError("Tenant key validation failed; check KMS recovery state") from None


async def assert_master_key_consistent(
    factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with factory() as session:
        result = await session.execute(select(TenantKey.encrypted_key, TenantKey.algorithm))
        validate_envelopes(master_key, list(result.all()))


async def verify_kms_on_startup() -> None:
    """Block production services before accepting traffic on inconsistent keys."""
    from app.core.config import get_settings
    from app.core.database import get_session_factory

    settings = get_settings()
    if not settings.is_production:
        return
    try:
        master_key = bytes.fromhex(settings.kms_master_key)
    except ValueError:
        raise RuntimeError("Invalid KMS master key configuration") from None
    await assert_master_key_consistent(get_session_factory(), master_key)
