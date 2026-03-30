"""Seed script — create initial super_admin and CRI-RSK tenant.

Usage: python -m app.scripts.seed
Requires: SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD env vars

Idempotent: safe to run multiple times (skips existing records).
"""

import asyncio
import os
import sys

import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import close_engine, get_engine, get_session_factory
from app.core.logging import setup_logging
from app.core.minio import init_minio
from app.core.qdrant import close_qdrant, init_qdrant
from app.core.redis import close_redis, init_redis
from app.models.admin import Admin
from app.models.enums import AdminRole
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate
from app.services.auth.service import AuthService
from app.services.tenant.provisioning import TenantProvisioningService

logger = structlog.get_logger()


async def seed() -> None:
    """Create the initial super_admin and CRI-RSK tenant."""
    # Read seed env vars
    email = os.environ.get("SEED_ADMIN_EMAIL")
    password = os.environ.get("SEED_ADMIN_PASSWORD")

    if not email or not password:
        print("ERROR: SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD are required")
        sys.exit(1)

    get_settings()
    setup_logging()
    log = logger.bind(script="seed")

    # Initialize connections
    log.info("seed_start", email=email)
    get_engine()
    await init_redis()
    await init_qdrant()
    init_minio()

    try:
        factory = get_session_factory()

        # ── Step 1: Create super_admin if not exists ──
        async with factory() as session:
            result = await session.execute(select(Admin).where(Admin.email == email))
            existing_admin = result.scalar_one_or_none()

        if existing_admin:
            log.info("admin_exists", email=email)
        else:
            async with factory() as session:
                admin = Admin(
                    email=email,
                    password_hash=AuthService.hash_password(password),
                    full_name="Super Admin CRI",
                    role=AdminRole.super_admin,
                    tenant_id=None,
                    is_active=True,
                )
                session.add(admin)
                await session.commit()
                log.info("admin_created", email=email, role="super_admin")

        # ── Step 2: Create CRI-RSK tenant if not exists ──
        async with factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.slug == "rabat"))
            existing_tenant = result.scalar_one_or_none()

        if existing_tenant:
            log.info("tenant_exists", slug="rabat")
        else:
            service = TenantProvisioningService()
            tenant_data = TenantCreate(
                name="CRI Rabat-Sale-Kenitra",
                slug="rabat",
                region="Rabat-Sale-Kenitra",
            )
            tenant = await service.provision_tenant(tenant_data)
            log.info(
                "tenant_created",
                slug=tenant.slug,
                tenant_id=str(tenant.id),
            )

        log.info("seed_complete")

    finally:
        await close_qdrant()
        await close_redis()
        await close_engine()


if __name__ == "__main__":
    asyncio.run(seed())
