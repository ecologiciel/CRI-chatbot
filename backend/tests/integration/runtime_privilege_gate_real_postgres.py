"""Exercise the read-only privilege gate against disposable PostgreSQL."""

import asyncio
import importlib.util

import asyncpg

from app.core.config import get_settings


async def main():
    settings = get_settings()
    if (settings.postgres_host, settings.postgres_db) != (
        "codex-privilege-pg",
        "ragtest_privilege",
    ):
        raise RuntimeError("Refusing to run outside the privilege fixture")
    spec = importlib.util.spec_from_file_location("privilege_gate", "/tmp/privilege_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        await connection.execute("""
          CREATE TABLE public.audit_logs (id integer);
          CREATE TABLE public.alembic_version (version_num text);
          CREATE ROLE fixture_runtime LOGIN NOINHERIT;
          CREATE ROLE fixture_inherited NOLOGIN;
          GRANT USAGE ON SCHEMA public TO fixture_runtime;
          GRANT SELECT, INSERT ON public.audit_logs TO fixture_runtime;
        """)
        assert await module.inspect_role(connection, "fixture_runtime") == []
        assert await module.inspect_role(connection, "missing") == ["candidate role does not exist"]
        await connection.execute("""
          GRANT UPDATE ON public.audit_logs TO fixture_inherited;
          GRANT fixture_inherited TO fixture_runtime;
        """)
        assert "candidate can modify audit records" in await module.inspect_role(
            connection, "fixture_runtime"
        )
        await connection.execute("REVOKE fixture_inherited FROM fixture_runtime")
        await connection.execute("ALTER TABLE public.audit_logs OWNER TO fixture_runtime")
        assert "candidate can assume the audit table owner" in await module.inspect_role(
            connection, "fixture_runtime"
        )
        assert "candidate can assume a privileged role" in await module.inspect_role(
            connection, settings.postgres_user
        )
        print("PRIVILEGE_GATE_INHERITED_OWNER_SUPERUSER_OK", flush=True)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
