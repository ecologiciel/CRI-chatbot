"""Multi-tenant context, resolver, and FastAPI dependency.

TenantContext is injected into request.state by TenantMiddleware.
Services access it via: tenant = Depends(get_current_tenant)

Resolution strategies:
  - X-Tenant-ID header (back-office API)
  - phone_number_id (WhatsApp webhooks)
  - slug (internal utility)
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.exceptions import (
    TenantInactiveError,
    TenantNotFoundError,
    TenantResolutionError,
)
from app.models.enums import TenantStatus

if TYPE_CHECKING:
    from app.models.tenant import Tenant

logger = structlog.get_logger()

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable tenant identity for the current request.

    Provides scoped accessors for all per-tenant resources:
    PostgreSQL schema, Qdrant collection, Redis prefix, MinIO bucket.
    """

    id: uuid.UUID
    slug: str
    name: str
    status: str
    whatsapp_config: dict | None

    def __post_init__(self) -> None:
        # Defense-in-depth: prevent SQL injection in SET search_path
        if not _SLUG_PATTERN.match(self.slug):
            raise ValueError(f"Invalid tenant slug: {self.slug!r}")

    @property
    def db_schema(self) -> str:
        """PostgreSQL schema name: tenant_{{slug}}."""
        return f"tenant_{self.slug}"

    @property
    def qdrant_collection(self) -> str:
        """Qdrant collection name: kb_{{slug}}."""
        return f"kb_{self.slug}"

    @property
    def redis_prefix(self) -> str:
        """Redis key prefix: {{slug}}."""
        return self.slug

    @property
    def minio_bucket(self) -> str:
        """MinIO bucket name: cri-{{slug}}."""
        return f"cri-{self.slug}"

    @asynccontextmanager
    async def db_session(self) -> AsyncGenerator[AsyncSession]:
        """Yield an async DB session scoped to this tenant's schema.

        Sets search_path to tenant_{slug}, public so all queries
        resolve to the tenant's schema first.
        """
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text(f"SET search_path TO {self.db_schema}, public"))
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


class TenantResolver:
    """Resolve an active tenant from authoritative database state.

    Cached tenant records can outlive deactivation or phone reassignment.
    Every new request or job therefore checks the current database record.
    This does not cancel work that already resolved a tenant.
    """

    # Kept for components that invalidate caches created by older releases.
    REDIS_TENANT_CACHE_PREFIX = "tenant_cache"
    REDIS_PHONE_MAPPING_PREFIX = "phone_mapping"

    @staticmethod
    async def from_tenant_id_header(tenant_id: str) -> TenantContext:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except (ValueError, TypeError, AttributeError) as err:
            raise TenantNotFoundError(
                f"Invalid tenant ID format: {tenant_id}", details={"identifier": tenant_id}
            ) from err

        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.id == tenant_uuid))
            tenant = result.scalar_one_or_none()
        if not tenant:
            raise TenantNotFoundError(
                f"Tenant not found: {tenant_id}", details={"identifier": tenant_id}
            )
        if tenant.status != TenantStatus.active:
            raise TenantInactiveError(
                f"Tenant is not active: {tenant.slug}",
                details={"slug": tenant.slug, "status": tenant.status.value},
            )
        return TenantResolver._build_context(tenant)

    @staticmethod
    async def from_phone_number_id(phone_number_id: str) -> TenantContext:
        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Tenant).where(
                    Tenant.whatsapp_config["phone_number_id"].as_string() == phone_number_id,
                    Tenant.status == TenantStatus.active,
                )
            )
            tenant = result.scalar_one_or_none()
        if not tenant:
            raise TenantNotFoundError(
                f"No active tenant for phone_number_id: {phone_number_id}",
                details={"phone_number_id": phone_number_id},
            )
        return TenantResolver._build_context(tenant)

    @staticmethod
    async def from_slug(slug: str) -> TenantContext:
        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.slug == slug))
            tenant = result.scalar_one_or_none()
        if not tenant:
            raise TenantNotFoundError(f"Tenant not found: {slug}", details={"slug": slug})
        if tenant.status != TenantStatus.active:
            raise TenantInactiveError(
                f"Tenant is not active: {slug}",
                details={"slug": slug, "status": tenant.status.value},
            )
        return TenantResolver._build_context(tenant)

    # --- Internal helpers ---

    @staticmethod
    def _build_context(tenant: Tenant) -> TenantContext:  # noqa: F821
        """Convert a Tenant ORM object to TenantContext."""
        return TenantContext(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            status=tenant.status.value,
            whatsapp_config=tenant.whatsapp_config,
        )

    @staticmethod
    def _build_context_from_dict(data: dict) -> TenantContext:
        """Reconstruct TenantContext from a Redis-cached dict."""
        return TenantContext(
            id=uuid.UUID(data["id"]),
            slug=data["slug"],
            name=data["name"],
            status=data["status"],
            whatsapp_config=data.get("whatsapp_config"),
        )

    @staticmethod
    def _context_to_dict(ctx: TenantContext) -> dict:
        """Serialize TenantContext for Redis caching."""
        return {
            "id": str(ctx.id),
            "slug": ctx.slug,
            "name": ctx.name,
            "status": ctx.status,
            "whatsapp_config": ctx.whatsapp_config,
        }


async def get_current_tenant(request: Request) -> TenantContext:
    """FastAPI dependency — extract tenant from request.state.

    Usage:
        @router.get("/items")
        async def list_items(tenant: TenantContext = Depends(get_current_tenant)):
            async with tenant.db_session() as session:
                ...
    """
    tenant: TenantContext | None = getattr(request.state, "tenant", None)
    if tenant is None:
        raise TenantResolutionError(
            "Tenant context not available. Ensure TenantMiddleware is active.",
        )
    return tenant
