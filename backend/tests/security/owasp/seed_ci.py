"""Create explicit OWASP fixtures in a disposable CI database only."""

import asyncio
import os
import uuid

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import close_engine, get_session_factory
from app.models.admin import Admin
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.services.auth.service import AuthService
from app.services.tenant.provisioning import TenantProvisioningService
from tests.security.owasp.conftest import (
    ADMIN_A_EMAIL,
    ADMIN_A_PASSWORD,
    ADMIN_B_EMAIL,
    ADMIN_B_PASSWORD,
    SUPER_ADMIN_EMAIL,
    SUPER_ADMIN_PASSWORD,
    TENANT_A_ID,
    TENANT_A_SLUG,
    TENANT_B_ID,
    TENANT_B_SLUG,
    VIEWER_EMAIL,
    VIEWER_PASSWORD,
)


async def main() -> None:
    settings = get_settings()
    if (
        os.environ.get("OWASP_ASGI_ISOLATED") != "1"
        or settings.postgres_db != "owasp_ci"
        or settings.is_production
        or settings.postgres_host not in {"localhost", "127.0.0.1", "postgres"}
    ):
        raise RuntimeError("Refusing to seed outside the isolated OWASP CI environment")
    factory = get_session_factory()
    async with factory() as db:
        if await db.scalar(select(func.count()).select_from(Tenant)):
            raise RuntimeError("Refusing to seed a database containing tenants")
        if await db.scalar(select(func.count()).select_from(Admin)):
            raise RuntimeError("Refusing to seed a database containing administrators")
        db.add_all(
            [
                Tenant(
                    id=uuid.UUID(TENANT_A_ID),
                    name="OWASP A",
                    slug=TENANT_A_SLUG,
                    region="Test",
                    status=TenantStatus.active,
                ),
                Tenant(
                    id=uuid.UUID(TENANT_B_ID),
                    name="OWASP B",
                    slug=TENANT_B_SLUG,
                    region="Test",
                    status=TenantStatus.active,
                ),
            ]
        )
        await db.commit()
    provisioner = TenantProvisioningService()
    for slug in (TENANT_A_SLUG, TENANT_B_SLUG):
        await provisioner._create_schema(slug)
    async with factory() as db:
        for email, password, role, tenant_id in [
            (ADMIN_A_EMAIL, ADMIN_A_PASSWORD, AdminRole.admin_tenant, TENANT_A_ID),
            (ADMIN_B_EMAIL, ADMIN_B_PASSWORD, AdminRole.admin_tenant, TENANT_B_ID),
            (VIEWER_EMAIL, VIEWER_PASSWORD, AdminRole.viewer, TENANT_A_ID),
            (SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD, AdminRole.super_admin, None),
        ]:
            db.add(
                Admin(
                    email=email,
                    password_hash=AuthService.hash_password(password),
                    full_name="OWASP test",
                    role=role,
                    tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                    is_active=True,
                )
            )
        await db.commit()
    await close_engine()
    print("Isolated OWASP fixtures created")


if __name__ == "__main__":
    asyncio.run(main())
