"""Create the first super-admin for a clean demonstration deployment.

Unlike the legacy seed script, this bootstrap intentionally does not create a
sample CRI tenant.  The first tenant is provisioned separately for the
prospect being demonstrated.
"""

from __future__ import annotations

import asyncio
import os
import sys

import structlog
from sqlalchemy import select

from app.core.database import close_engine, get_engine, get_session_factory
from app.core.logging import setup_logging
from app.models.admin import Admin
from app.models.enums import AdminRole
from app.services.auth.service import AuthService

logger = structlog.get_logger()


async def bootstrap() -> None:
    """Idempotently create the configured super-admin."""
    email = os.environ.get("SEED_ADMIN_EMAIL")
    password = os.environ.get("SEED_ADMIN_PASSWORD")
    if not email or not password:
        print("SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD are required", file=sys.stderr)
        raise SystemExit(1)

    setup_logging()
    get_engine()
    try:
        async with get_session_factory()() as session:
            existing = await session.execute(select(Admin).where(Admin.email == email))
            if existing.scalar_one_or_none() is not None:
                logger.info("demo_super_admin_exists", email=email)
                return

            session.add(
                Admin(
                    email=email,
                    password_hash=AuthService.hash_password(password),
                    full_name="Super Admin Démonstration",
                    role=AdminRole.super_admin,
                    tenant_id=None,
                    is_active=True,
                )
            )
            await session.commit()
            logger.info("demo_super_admin_created", email=email)
    finally:
        await close_engine()


if __name__ == "__main__":
    asyncio.run(bootstrap())
