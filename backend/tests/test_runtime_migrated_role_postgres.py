"""Exercise a non-superuser login only against a disposable migrated database."""
import importlib.util
import os
import secrets
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

URL = os.getenv("TEST_RUNTIME_ROLE_MIGRATED_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")
ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_migrated_schema_limited_login_can_insert_but_not_alter_audit():
    url = make_url(URL).set(drivername="postgresql")
    if not url.database or not url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing to run outside a disposable ragtest_ database")
    admin = await asyncpg.connect(url.render_as_string(hide_password=False))
    runtime = None
    created_group = created_login = False
    login = "fixture_runtime_" + uuid.uuid4().hex[:12]
    password = secrets.token_hex(24)
    audit_id = uuid.uuid4()
    try:
        assert await admin.fetchval("SELECT current_database()") == url.database
        assert not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cri_runtime_access')")
        sql = (ROOT / "scripts/prepare-runtime-db-role.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
        refresh = (ROOT / "scripts/rehearse-refresh-runtime-grants.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
        await admin.execute(sql.replace("\\ir rehearse-refresh-runtime-grants.sql", refresh))
        created_group = True
        await admin.execute(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}' IN ROLE cri_runtime_access")
        created_login = True
        runtime_url = url.set(username=login, password=password)
        runtime = await asyncpg.connect(runtime_url.render_as_string(hide_password=False))
        spec = importlib.util.spec_from_file_location("runtime_gate", ROOT / "scripts/check_runtime_db_privileges.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert await module.inspect_role(admin, login) == []
        await runtime.execute("INSERT INTO public.audit_logs (id,tenant_slug,user_type,action,resource_type) VALUES ($1,'fixture','system','test','fixture')", audit_id)
        assert await runtime.fetchval("SELECT count(*) FROM public.audit_logs WHERE id=$1", audit_id) == 1
        assert await runtime.fetchval("SELECT has_table_privilege(current_user, 'public.agent_reply_outbox_events', 'INSERT')")
        assert await runtime.fetchval("SELECT has_table_privilege(current_user, 'tenant_template.contacts', 'SELECT')")
        for command in ("UPDATE public.audit_logs SET action='tampered'", "DELETE FROM public.audit_logs", "TRUNCATE public.audit_logs", "UPDATE public.alembic_version SET version_num='forged'"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await runtime.execute(command)
    finally:
        if runtime:
            await runtime.close()
        await admin.execute("DELETE FROM public.audit_logs WHERE id=$1", audit_id)
        if created_login:
            await admin.execute(f"DROP ROLE {login}")
        if created_group:
            await admin.execute("DROP OWNED BY cri_runtime_access")
            await admin.execute("DROP ROLE cri_runtime_access")
        await admin.close()
