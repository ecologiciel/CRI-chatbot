"""Multi-tenant context, resolver, and FastAPI dependency.

TenantContext is injected into request.state by TenantMiddleware.
Services access it via: tenant = Depends(get_current_tenant)

Resolution strategies:
  - X-Tenant-ID header (back-office API)
  - phone_number_id (WhatsApp webhooks)
  - slug (internal utility)
"""

import json
import re
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

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
from app.core.redis import get_redis
from app.models.enums import TenantStatus

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
            await session.execute(
                text(f"SET search_path TO {self.db_schema}, public")
            )
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


class TenantResolver:
    """Resolves tenant identity from various request sources.

    Each method checks Redis cache first, then falls back to DB.
    Successful lookups are cached in Redis for subsequent requests.
    """

    REDIS_PHONE_MAPPING_PREFIX = "phone_mapping"
    REDIS_TENANT_CACHE_PREFIX = "tenant_cache"
    REDIS_TENANT_CACHE_TTL = 300  # 5 minutes
    REDIS_PHONE_MAPPING_TTL = 3600  # 1 hour

    @staticmethod
    async def from_tenant_id_header(tenant_id: str) -> TenantContext:
        """Resolve tenant from X-Tenant-ID header (back-office).

        Args:
            tenant_id: UUID string from X-Tenant-ID header.

        Returns:
            TenantContext for the resolved tenant.

        Raises:
            TenantNotFoundError: If tenant UUID does not exist.
            TenantInactiveError: If tenant is not active.
        """
        redis = get_redis()

        # 1. Redis cache lookup
        cache_key = f"{TenantResolver.REDIS_TENANT_CACHE_PREFIX}:{tenant_id}"
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            if data["status"] != TenantStatus.active.value:
                raise TenantInactiveError(
                    f"Tenant is not active: {data['slug']}",
                    details={"slug": data["slug"], "status": data["status"]},
                )
            return TenantResolver._build_context_from_dict(data)

        # 2. DB fallback
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            raise TenantNotFoundError(
                f"Invalid tenant ID format: {tenant_id}",
                details={"identifier": tenant_id},
            )

        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_uuid)
            )
            tenant = result.scalar_one_or_none()

        if not tenant:
            raise TenantNotFoundError(
                f"Tenant not found: {tenant_id}",
                details={"identifier": tenant_id},
            )

        if tenant.status != TenantStatus.active:
            raise TenantInactiveError(
                f"Tenant is not active: {tenant.slug}",
                details={"slug": tenant.slug, "status": tenant.status.value},
            )

        context = TenantResolver._build_context(tenant)
        await redis.setex(
            cache_key,
            TenantResolver.REDIS_TENANT_CACHE_TTL,
            json.dumps(TenantResolver._context_to_dict(context)),
        )
        logger.debug("tenant_cached", tenant_slug=context.slug, cache_key=cache_key)
        return context

    @staticmethod
    async def from_phone_number_id(phone_number_id: str) -> TenantContext:
        """Resolve tenant from WhatsApp phone_number_id.

        Args:
            phone_number_id: The phone_number_id from the WhatsApp webhook payload.

        Returns:
            TenantContext for the resolved active tenant.

        Raises:
            TenantNotFoundError: If no active tenant matches this phone_number_id.
        """
        redis = get_redis()

        # 1. Redis cache lookup
        cache_key = f"{TenantResolver.REDIS_PHONE_MAPPING_PREFIX}:{phone_number_id}"
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return TenantResolver._build_context_from_dict(data)

        # 2. DB fallback — JSONB query
        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Tenant).where(
                    Tenant.whatsapp_config["phone_number_id"].as_string()
                    == phone_number_id,
                    Tenant.status == TenantStatus.active,
                )
            )
            tenant = result.scalar_one_or_none()

        if not tenant:
            raise TenantNotFoundError(
                f"No active tenant for phone_number_id: {phone_number_id}",
                details={"phone_number_id": phone_number_id},
            )

        context = TenantResolver._build_context(tenant)
        await redis.setex(
            cache_key,
            TenantResolver.REDIS_PHONE_MAPPING_TTL,
            json.dumps(TenantResolver._context_to_dict(context)),
        )
        logger.debug(
            "phone_mapping_cached",
            tenant_slug=context.slug,
            phone_number_id=phone_number_id,
        )
        return context

    @staticmethod
    async def from_slug(slug: str) -> TenantContext:
        """Resolve tenant from slug (internal utility).

        Args:
            slug: Tenant slug identifier.

        Returns:
            TenantContext for the resolved tenant.

        Raises:
            TenantNotFoundError: If slug does not exist.
            TenantInactiveError: If tenant is not active.
        """
        redis = get_redis()

        # 1. Redis cache lookup
        cache_key = f"{TenantResolver.REDIS_TENANT_CACHE_PREFIX}:slug:{slug}"
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            if data["status"] != TenantStatus.active.value:
                raise TenantInactiveError(
                    f"Tenant is not active: {slug}",
                    details={"slug": slug, "status": data["status"]},
                )
            return TenantResolver._build_context_from_dict(data)

        # 2. DB fallback
        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.slug == slug)
            )
            tenant = result.scalar_one_or_none()

        if not tenant:
            raise TenantNotFoundError(
                f"Tenant not found: {slug}",
                details={"slug": slug},
            )

        if tenant.status != TenantStatus.active:
            raise TenantInactiveError(
                f"Tenant is not active: {slug}",
                details={"slug": slug, "status": tenant.status.value},
            )

        context = TenantResolver._build_context(tenant)
        await redis.setex(
            cache_key,
            TenantResolver.REDIS_TENANT_CACHE_TTL,
            json.dumps(TenantResolver._context_to_dict(context)),
        )
        return context

    # --- Internal helpers ---

    @staticmethod
    def _build_context(tenant: "Tenant") -> TenantContext:  # noqa: F821
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
