"""Atomic tenant provisioning with rollback on failure.

Creates all per-tenant resources: PostgreSQL schema (cloned from
tenant_template), Qdrant collection, Redis phone mapping, MinIO bucket.
If any step fails, previously completed steps are rolled back.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from qdrant_client.models import Distance, VectorParams
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.database import get_session_factory
from app.core.exceptions import DuplicateTenantError, TenantProvisioningError
from app.core.minio import get_minio
from app.core.qdrant import get_qdrant
from app.core.redis import get_redis
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate

logger = structlog.get_logger()

# Embedding dimension for text-embedding-004 / multilingual-e5-large
EMBEDDING_DIMENSION = 768

# Tables to clone from tenant_template, in FK-dependency order.
# Parent tables first, then children.
_TEMPLATE_TABLES = [
    "contacts",
    "kb_documents",
    "conversations",
    "messages",
    "kb_chunks",
    "feedback",
    "unanswered_questions",
]

# Cross-table FK constraints to re-create after cloning.
# (table, constraint_name, column, ref_table, ref_column, on_delete)
_FK_CONSTRAINTS: list[tuple[str, str, str, str, str, str]] = [
    ("conversations", "fk_conv_contact", "contact_id", "contacts", "id", "CASCADE"),
    ("messages", "fk_msg_conversation", "conversation_id", "conversations", "id", "CASCADE"),
    ("kb_chunks", "fk_chunk_document", "document_id", "kb_documents", "id", "CASCADE"),
    ("feedback", "fk_feedback_message", "message_id", "messages", "id", "CASCADE"),
]

# Cross-schema FK (references public.admins)
_CROSS_SCHEMA_FK = (
    "unanswered_questions",
    "fk_uq_reviewer",
    "reviewed_by",
    "public.admins",
    "id",
    "SET NULL",
)


class TenantProvisioningService:
    """Atomic provisioning of new tenants with rollback on failure."""

    def __init__(self) -> None:
        self.logger = logger.bind(service="tenant_provisioning")

    async def provision_tenant(self, data: TenantCreate) -> Tenant:
        """Full provisioning pipeline with automatic rollback.

        Steps: DB record → PG schema → Qdrant collection →
               Redis mapping → MinIO bucket → activate.

        Args:
            data: Validated tenant creation payload.

        Returns:
            Created Tenant ORM object with status=ACTIVE.

        Raises:
            DuplicateTenantError: If slug already exists.
            TenantProvisioningError: If any step fails (auto-rollback).
        """
        rollback_stack: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = []
        tenant: Tenant | None = None
        log = self.logger.bind(slug=data.slug)

        try:
            # Step 1: Create tenant record (status=provisioning)
            tenant = await self._create_tenant_record(data)
            rollback_stack.append(("db_record", lambda: self._delete_tenant_record(tenant.id)))
            log.info("step_completed", step="db_record", tenant_id=str(tenant.id))

            # Step 2: Clone PostgreSQL schema from tenant_template
            await self._create_schema(data.slug)
            rollback_stack.append(("pg_schema", lambda: self._drop_schema(data.slug)))
            log.info("step_completed", step="pg_schema")

            # Step 3: Create Qdrant collection
            await self._create_qdrant_collection(data.slug)
            rollback_stack.append(("qdrant_collection", lambda: self._delete_qdrant_collection(data.slug)))
            log.info("step_completed", step="qdrant_collection")

            # Step 4: Redis phone mapping (if WhatsApp config provided)
            if data.whatsapp_config and data.whatsapp_config.get("phone_number_id"):
                phone_number_id = data.whatsapp_config["phone_number_id"]
                await self._create_redis_mapping(tenant, phone_number_id)
                rollback_stack.append(
                    ("redis_mapping", lambda: self._delete_redis_mapping(phone_number_id))
                )
                log.info("step_completed", step="redis_mapping", phone_number_id=phone_number_id)

            # Step 5: Create MinIO bucket
            await self._create_minio_bucket(data.slug)
            rollback_stack.append(("minio_bucket", lambda: self._delete_minio_bucket(data.slug)))
            log.info("step_completed", step="minio_bucket")

            # Step 6: Activate tenant
            await self._activate_tenant(tenant.id)
            log.info("tenant_provisioned", tenant_id=str(tenant.id))

            # Refresh tenant object with active status
            tenant.status = TenantStatus.active
            return tenant

        except (DuplicateTenantError, TenantProvisioningError):
            await self._rollback(rollback_stack, data.slug)
            raise
        except Exception as exc:
            log.error("provisioning_failed", error=str(exc))
            await self._rollback(rollback_stack, data.slug)
            raise TenantProvisioningError(
                f"Provisioning failed for {data.slug}: {exc}"
            ) from exc

    async def deprovision_tenant(self, slug: str) -> None:
        """Remove all resources for a tenant.

        Continues on partial failure so as many resources as possible
        are cleaned up. Super-admin only.

        Args:
            slug: Tenant slug to deprovision.
        """
        log = self.logger.bind(slug=slug, action="deprovision")

        # 1. Set status to inactive
        try:
            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    select(Tenant).where(Tenant.slug == slug)
                )
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.status = TenantStatus.inactive
                    await session.commit()
                    log.info("step_completed", step="deactivated")
        except Exception as exc:
            log.error("deprovision_step_failed", step="deactivate", error=str(exc))

        # 2. Delete MinIO bucket (must empty first)
        try:
            await self._empty_and_remove_bucket(slug)
            log.info("step_completed", step="minio_removed")
        except Exception as exc:
            log.error("deprovision_step_failed", step="minio", error=str(exc))

        # 3. Delete Redis mappings
        try:
            redis = get_redis()
            # Clean up tenant cache and phone mapping
            if tenant and tenant.whatsapp_config:
                phone_id = tenant.whatsapp_config.get("phone_number_id")
                if phone_id:
                    await redis.delete(f"phone_mapping:{phone_id}")
            await redis.delete(f"tenant_cache:{tenant.id}" if tenant else "")
            await redis.delete(f"tenant_cache:slug:{slug}")
            log.info("step_completed", step="redis_cleaned")
        except Exception as exc:
            log.error("deprovision_step_failed", step="redis", error=str(exc))

        # 4. Delete Qdrant collection
        try:
            await self._delete_qdrant_collection(slug)
            log.info("step_completed", step="qdrant_removed")
        except Exception as exc:
            log.error("deprovision_step_failed", step="qdrant", error=str(exc))

        # 5. Drop PostgreSQL schema
        try:
            await self._drop_schema(slug)
            log.info("step_completed", step="schema_dropped")
        except Exception as exc:
            log.error("deprovision_step_failed", step="pg_schema", error=str(exc))

        # 6. Delete tenant record
        try:
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.slug == slug)
                )
                await session.commit()
            log.info("step_completed", step="record_deleted")
        except Exception as exc:
            log.error("deprovision_step_failed", step="db_record", error=str(exc))

        log.info("tenant_deprovisioned")

    # ── Private step methods ──

    async def _create_tenant_record(self, data: TenantCreate) -> Tenant:
        """Insert tenant row in public.tenants with status=provisioning."""
        factory = get_session_factory()
        async with factory() as session:
            # Check for existing slug
            existing = await session.execute(
                select(Tenant.id).where(Tenant.slug == data.slug)
            )
            if existing.scalar_one_or_none():
                raise DuplicateTenantError(data.slug)

            tenant = Tenant(
                name=data.name,
                slug=data.slug,
                region=data.region,
                logo_url=data.logo_url,
                whatsapp_config=data.whatsapp_config,
                status=TenantStatus.provisioning,
            )
            # Copy optional limit fields if provided
            if hasattr(data, "accent_color") and data.accent_color:
                tenant.accent_color = data.accent_color
            if hasattr(data, "max_contacts") and data.max_contacts is not None:
                tenant.max_contacts = data.max_contacts
            if hasattr(data, "max_messages_per_year") and data.max_messages_per_year is not None:
                tenant.max_messages_per_year = data.max_messages_per_year
            if hasattr(data, "max_admins") and data.max_admins is not None:
                tenant.max_admins = data.max_admins

            session.add(tenant)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateTenantError(data.slug) from exc

            await session.refresh(tenant)
            return tenant

    async def _create_schema(self, slug: str) -> None:
        """Clone tenant_template schema to tenant_{slug}.

        Creates the schema, copies all tables with LIKE ... INCLUDING ALL,
        then re-creates cross-table foreign key constraints.
        """
        schema = f"tenant_{slug}"
        factory = get_session_factory()
        async with factory() as session:
            # Create the schema
            await session.execute(text(f"CREATE SCHEMA {schema}"))

            # Clone each table from tenant_template
            for table in _TEMPLATE_TABLES:
                await session.execute(
                    text(
                        f"CREATE TABLE {schema}.{table} "
                        f"(LIKE tenant_template.{table} INCLUDING ALL)"
                    )
                )

            # Re-create intra-schema foreign keys
            for table, constraint, column, ref_table, ref_col, on_del in _FK_CONSTRAINTS:
                await session.execute(
                    text(
                        f"ALTER TABLE {schema}.{table} "
                        f"ADD CONSTRAINT {constraint} "
                        f"FOREIGN KEY ({column}) "
                        f"REFERENCES {schema}.{ref_table}({ref_col}) "
                        f"ON DELETE {on_del}"
                    )
                )

            # Cross-schema FK: unanswered_questions.reviewed_by → public.admins.id
            tbl, constraint, col, ref_tbl, ref_col, on_del = _CROSS_SCHEMA_FK
            await session.execute(
                text(
                    f"ALTER TABLE {schema}.{tbl} "
                    f"ADD CONSTRAINT {constraint} "
                    f"FOREIGN KEY ({col}) "
                    f"REFERENCES {ref_tbl}({ref_col}) "
                    f"ON DELETE {on_del}"
                )
            )

            await session.commit()

    async def _create_qdrant_collection(self, slug: str) -> None:
        """Create Qdrant collection kb_{slug} for vector search."""
        qdrant = get_qdrant()
        collection_name = f"kb_{slug}"
        await qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )

    async def _create_redis_mapping(self, tenant: Tenant, phone_number_id: str) -> None:
        """Map phone_number_id → tenant data in Redis for webhook resolution."""
        redis = get_redis()
        mapping_data = json.dumps({
            "id": str(tenant.id),
            "slug": tenant.slug,
            "name": tenant.name,
            "status": TenantStatus.active.value,
            "whatsapp_config": tenant.whatsapp_config,
        })
        await redis.set(
            f"phone_mapping:{phone_number_id}",
            mapping_data,
        )

    async def _create_minio_bucket(self, slug: str) -> None:
        """Create MinIO bucket cri-{slug}."""
        minio = get_minio()
        bucket_name = f"cri-{slug}"
        bucket_exists = await minio.bucket_exists(bucket_name)
        if not bucket_exists:
            await minio.make_bucket(bucket_name)

    async def _activate_tenant(self, tenant_id: uuid.UUID) -> None:
        """Update tenant status from provisioning to active."""
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(status=TenantStatus.active)
            )
            await session.commit()

    # ── Rollback helpers ──

    async def _rollback(
        self,
        stack: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        slug: str,
    ) -> None:
        """Execute rollback stack in reverse order, logging each step."""
        log = self.logger.bind(slug=slug, action="rollback")
        for step_name, undo_fn in reversed(stack):
            try:
                await undo_fn()
                log.info("rollback_step_completed", step=step_name)
            except Exception as exc:
                log.error("rollback_step_failed", step=step_name, error=str(exc))

    async def _delete_tenant_record(self, tenant_id: uuid.UUID) -> None:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                delete(Tenant).where(Tenant.id == tenant_id)
            )
            await session.commit()

    async def _drop_schema(self, slug: str) -> None:
        schema = f"tenant_{slug}"
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            await session.commit()

    async def _delete_qdrant_collection(self, slug: str) -> None:
        qdrant = get_qdrant()
        await qdrant.delete_collection(collection_name=f"kb_{slug}")

    async def _delete_redis_mapping(self, phone_number_id: str) -> None:
        redis = get_redis()
        await redis.delete(f"phone_mapping:{phone_number_id}")

    async def _delete_minio_bucket(self, slug: str) -> None:
        minio = get_minio()
        bucket_name = f"cri-{slug}"
        if await minio.bucket_exists(bucket_name):
            await minio.remove_bucket(bucket_name)

    async def _empty_and_remove_bucket(self, slug: str) -> None:
        """Empty and remove a MinIO bucket (for deprovisioning)."""
        minio = get_minio()
        bucket_name = f"cri-{slug}"
        if not await minio.bucket_exists(bucket_name):
            return

        # List and delete all objects before removing bucket.
        # miniopy_async.list_objects returns an async iterator directly
        # (not a coroutine), so no await on the call itself.
        objects = minio.list_objects(bucket_name, recursive=True)
        async for obj in objects:
            await minio.remove_object(bucket_name, obj.object_name)

        await minio.remove_bucket(bucket_name)
