"""Check audit persistence and failure reporting on an isolated database."""

import asyncio

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import close_engine, get_engine, get_session_factory
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogCreate
from app.services.audit.service import AuditService


async def main():
    settings = get_settings()
    if (settings.postgres_host, settings.postgres_db) != ("codex-audit-pg", "ragtest_audit"):
        raise RuntimeError("Refusing to run outside the audit fixture")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: AuditLog.__table__.create(sync))
    entry = AuditLogCreate(
        tenant_slug="fixture", user_type="system", action="create", resource_type="test"
    )
    service = AuditService()
    assert await service.log_action(entry) is True
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE public.audit_logs RENAME TO audit_fixture_unavailable"))
    assert await service.log_action(entry) is False
    await close_engine()
    print("AUDIT_REAL_POSTGRES_SUCCESS_AND_FAILURE_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
