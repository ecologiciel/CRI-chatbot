"""Exercise a restricted login on a disposable migrated production schema."""

import asyncio

import asyncpg

from app.core.config import get_settings


async def main():
    settings = get_settings()
    if (settings.postgres_host, settings.postgres_db, settings.postgres_user) != (
        "codex-db-credential-pg",
        "ragtest_dbcredentials",
        "fixture_runtime",
    ):
        raise RuntimeError("Refusing to run outside the credential fixture")
    assert settings.runtime_db_user_present == settings.runtime_db_password_present == "1"
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    try:
        assert await connection.fetchval("SELECT current_user") == "fixture_runtime"
        await connection.execute("""
            INSERT INTO public.audit_logs (tenant_slug,user_type,action,resource_type)
            VALUES ('fixture','system','create','test')
        """)
        for sql in (
            "UPDATE public.audit_logs SET action='delete'",
            "DELETE FROM public.audit_logs",
            "TRUNCATE public.audit_logs",
            "INSERT INTO public.alembic_version (version_num) VALUES ('forged')",
        ):
            try:
                await connection.execute(sql)
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("Restricted operation unexpectedly succeeded")
        print("RESTRICTED_RUNTIME_AUDIT_AND_MIGRATION_GUARD_OK", flush=True)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
