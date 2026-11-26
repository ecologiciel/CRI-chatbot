"""Guard an inbox operation against tenant removal and channel reassignment.

Staged component: no production worker uses this yet. The tenant row lock
is held for the operation and can delay configuration updates, so callers
must provide a bounded timeout and avoid re-entering a tenant-row write.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.exceptions import TenantInactiveError
from app.core.tenant import TenantContext, TenantResolver
from app.core.tenant_lifecycle import protect_ingestion
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.services.whatsapp.inbox_leases import InboxClaim


@asynccontextmanager
async def protect_claim_channel(claim: InboxClaim) -> AsyncIterator[TenantContext]:
    """Pin the authoritative tenant and channel until the operation finishes."""
    initial = await TenantResolver.from_tenant_id_header(str(claim.tenant_id))
    async with protect_ingestion(initial), get_session_factory()() as session:
        current = (
            await session.execute(
                select(Tenant).where(Tenant.id == claim.tenant_id).with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if (
            current is None
            or current.slug != initial.slug
            or current.status != TenantStatus.active
            or (current.whatsapp_config or {}).get("phone_number_id") != claim.phone_number_id
        ):
            raise TenantInactiveError("WhatsApp channel is inactive or has changed")
        yield TenantResolver._build_context(current)
