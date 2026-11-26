"""PostgreSQL lifecycle locks for tenant-scoped publication and removal.

Shared locks let ingestion jobs for one tenant run concurrently. A nonblocking
exclusive lock lets removal fail safely if any protected job is in flight.
Locks are transaction-scoped and release automatically on connection loss.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select, text

from app.core.database import get_session_factory
from app.core.exceptions import TenantInactiveError, TenantLifecycleBusyError
from app.core.tenant import TenantContext
from app.models.enums import TenantStatus
from app.models.tenant import Tenant


def _lock_key(slug: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", slug):
        raise ValueError("Invalid tenant slug")
    return f"tenant-lifecycle:{slug}"


@asynccontextmanager
async def protect_ingestion(tenant: TenantContext) -> AsyncIterator[None]:
    """Hold a shared lock and recheck identity/status after acquiring it."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))"),
            {"key": _lock_key(tenant.slug)},
        )
        current = (
            await session.execute(
                select(Tenant.id, Tenant.status).where(Tenant.slug == tenant.slug)
            )
        ).one_or_none()
        if current is None or current.id != tenant.id or current.status != TenantStatus.active:
            raise TenantInactiveError("Institution inactive ou modifiée ; ingestion interrompue.")
        yield


@asynccontextmanager
async def protect_removal(slug: str) -> AsyncIterator[None]:
    """Refuse removal if protected work is currently in progress."""
    factory = get_session_factory()
    async with factory() as session:
        acquired = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": _lock_key(slug)},
            )
        ).scalar_one()
        if not acquired:
            raise TenantLifecycleBusyError(
                "Un traitement documentaire est en cours pour cette institution. Réessayez après sa fin."
            )
        yield
