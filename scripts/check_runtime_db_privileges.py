"""Read-only PostgreSQL gate for a proposed application login.

Run inside the backend container with DB_RUNTIME_ROLE set to the candidate.
Passing this gate alone does not prove isolation between tenant schemas.
"""

import asyncio
import os
import sys

import asyncpg

from app.core.config import get_settings


async def inspect_role(connection, role_name):
    row = await connection.fetchrow(
        """
        WITH candidate AS (SELECT * FROM pg_roles WHERE rolname=$1),
        reachable AS (
          SELECT parent.* FROM pg_roles parent, candidate c
          WHERE pg_has_role(c.oid, parent.oid, 'MEMBER')
        )
        SELECT c.rolcanlogin,
          EXISTS (SELECT 1 FROM reachable r WHERE r.rolsuper OR r.rolcreaterole
                  OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls) AS elevated,
          EXISTS (SELECT 1 FROM reachable r, pg_class t
                  WHERE t.oid='public.audit_logs'::regclass
                    AND pg_has_role(r.oid, t.relowner, 'MEMBER')) AS audit_owner,
          EXISTS (SELECT 1 FROM reachable r
                  WHERE has_table_privilege(r.oid,'public.audit_logs','UPDATE')
                     OR has_table_privilege(r.oid,'public.audit_logs','DELETE')
                     OR has_table_privilege(r.oid,'public.audit_logs','TRUNCATE')
                     OR has_table_privilege(r.oid,'public.audit_logs','TRIGGER')
                     OR has_table_privilege(r.oid,'public.audit_logs','REFERENCES')) AS audit_modify,
          EXISTS (SELECT 1 FROM reachable r
                  WHERE has_table_privilege(r.oid,'public.alembic_version','INSERT')
                     OR has_table_privilege(r.oid,'public.alembic_version','UPDATE')
                     OR has_table_privilege(r.oid,'public.alembic_version','DELETE')
                     OR has_table_privilege(r.oid,'public.alembic_version','TRUNCATE')) AS migration_modify,
          EXISTS (SELECT 1 FROM reachable r
                  WHERE has_schema_privilege(r.oid,'public','CREATE')) AS public_create,
          EXISTS (SELECT 1 FROM reachable r
                  JOIN pg_proc p ON has_function_privilege(r.oid,p.oid,'EXECUTE')
                  JOIN pg_namespace n ON n.oid=p.pronamespace
                  JOIN pg_roles owner ON owner.oid=p.proowner
                  WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema')
                    AND (owner.rolsuper
                         OR has_table_privilege(owner.oid,'public.audit_logs','UPDATE')
                         OR has_table_privilege(owner.oid,'public.audit_logs','DELETE')
                         OR has_table_privilege(owner.oid,'public.audit_logs','TRUNCATE'))) AS privileged_function,
          has_table_privilege(c.oid,'public.audit_logs','INSERT') AS audit_insert,
          has_table_privilege(c.oid,'public.audit_logs','SELECT') AS audit_select
        FROM candidate c
        """,
        role_name,
    )
    if row is None:
        return ["candidate role does not exist"]
    failures = []
    if not row["rolcanlogin"]:
        failures.append("candidate cannot log in")
    for name, message in (
        ("elevated", "candidate can assume a privileged role"),
        ("audit_owner", "candidate can assume the audit table owner"),
        ("audit_modify", "candidate can modify audit records"),
        ("migration_modify", "candidate can modify migration state"),
        ("public_create", "candidate can create objects in public"),
        (
            "privileged_function",
            "candidate can execute a privileged security-definer function; review required",
        ),
    ):
        if row[name]:
            failures.append(message)
    if not row["audit_insert"] or not row["audit_select"]:
        failures.append("candidate lacks direct audit insert or select access")
    return failures


async def main():
    role = os.environ.get("DB_RUNTIME_ROLE")
    if not role:
        print("DB_PRIVILEGE_CHECK: candidate role is required", file=sys.stderr)
        return 2
    settings = get_settings()
    connection = None
    try:
        connection = await asyncpg.connect(
            settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
            timeout=10,
        )
        failures = await inspect_role(connection, role)
    except Exception as exc:
        print(
            f"DB_PRIVILEGE_CHECK: unable to inspect ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    finally:
        if connection is not None:
            await connection.close()
    if failures:
        for failure in failures:
            print(f"DB_PRIVILEGE_FAIL: {failure}", file=sys.stderr)
        return 1
    print("DB_PRIVILEGE_CHECK_OK: audit and migration privileges are limited")
    print(
        "DB_PRIVILEGE_NOTE: tenant SQL isolation and runtime functionality are not covered"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
