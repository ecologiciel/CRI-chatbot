"""Transactional channel-config conversion; not a deployment entry point.

Call only with all channel writers stopped and a verified recovery plan. This
does not erase historical PostgreSQL WAL, replicas or backups.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.whatsapp.config_envelope import (
    is_sealed_or_malformed,
    open_channel_config,
    seal_channel_config,
)


async def seal_existing_channel_configs(
    session_factory,
    cipher: VersionedEnvelopeService,
    *,
    max_tenants: int = 10_000,
) -> dict[str, int]:
    """Seal and audit all configs in one transaction; any failure rolls back."""
    if not 1 <= max_tenants <= 100_000:
        raise ValueError("Invalid tenant migration limit")
    counts = {"sealed": 0, "already_sealed": 0, "without_config": 0}
    async with session_factory() as session, session.begin():
        tenants = (await session.execute(
            select(Tenant).order_by(Tenant.id).limit(max_tenants + 1).with_for_update()
        )).scalars().all()
        if len(tenants) > max_tenants:
            raise RuntimeError("Tenant count exceeds the configured migration limit")
        for tenant in tenants:
            config = tenant.whatsapp_config
            if config is None:
                counts["without_config"] += 1
                continue
            if not isinstance(config, dict):
                raise ValueError("Invalid channel configuration")
            if is_sealed_or_malformed(config):
                await open_channel_config(tenant.id, config, cipher, session=session)
                counts["already_sealed"] += 1
                continue
            sealed = await seal_channel_config(tenant.id, config, cipher, session=session)
            if await open_channel_config(tenant.id, sealed, cipher, session=session) != config:
                raise RuntimeError("Channel encryption verification failed")
            tenant.whatsapp_config = sealed
            session.add(AuditLog(
                tenant_slug=tenant.slug,
                user_type="system",
                action="wa_config_sealed",
                resource_type="tenant",
                resource_id=str(tenant.id),
                details={"key_version": sealed["_envelope"]["version"]},
            ))
            counts["sealed"] += 1
    return counts
