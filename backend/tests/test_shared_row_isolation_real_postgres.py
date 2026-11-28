"""Exercise experimental RLS with separate synthetic PostgreSQL logins."""
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.exceptions import CRIDecryptionError
from app.services.crypto.kms import KMSService

URL = os.getenv("TEST_WA_FENCE_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")
TABLES = ("agent_reply_outbox_events", "whatsapp_inbox_events", "whatsapp_status_events",
          "notification_outbox_events", "dossier_import_requests", "tenant_keys")


@pytest.mark.asyncio
async def test_shared_rows_follow_authenticated_login_not_caller_setting():
    elevated = create_async_engine(URL)
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    master_key = bytes.fromhex("07" * 32)
    data_keys = {tenant_a: os.urandom(32), tenant_b: os.urandom(32)}
    script = (Path(__file__).parents[2] / "scripts/rehearse-shared-row-isolation.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
    async with elevated.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        assert not await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('cri_rls_fixture','fixture_rls_a','fixture_rls_b','fixture_rls_unbound'))"))
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status) VALUES (:a,'A','fixture_rls_a','Test','active'),(:b,'B','fixture_rls_b','Test','active')"), {"a": tenant_a, "b": tenant_b})
        for tenant_id in (tenant_a, tenant_b):
            params = {"tenant": tenant_id, "id": uuid.uuid4()}
            await conn.execute(text("INSERT INTO public.agent_reply_outbox_events (id,tenant_id,request_key,actor_id,escalation_id,conversation_id,contact_id,phone_number_id,recipient_fingerprint,ciphertext,key_version) VALUES (:id,:tenant,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'123',repeat('a',64),'fixture',1)"), params)
            await conn.execute(text("INSERT INTO public.whatsapp_inbox_events (id,tenant_id,provider_message_id,phone_number_id,ciphertext,key_version) VALUES (:id,:tenant,'synthetic','123','fixture',1)"), params)
            await conn.execute(text("INSERT INTO public.whatsapp_status_events (id,tenant_id,phone_number_id,fingerprint,ciphertext,key_version) VALUES (:id,:tenant,'123',repeat('b',64),'fixture',1)"), params)
            await conn.execute(text("INSERT INTO public.notification_outbox_events (id,tenant_id,history_id,dossier_id) VALUES (:id,:tenant,gen_random_uuid(),gen_random_uuid())"), params)
            await conn.execute(text("INSERT INTO public.dossier_import_requests (id,tenant_id,object_key,content_sha256,mapping_sha256) VALUES (:id,:tenant,'fixture',repeat('c',64),repeat('d',64))"), params)
            nonce = os.urandom(12)
            params["wrapped"] = nonce + AESGCM(master_key).encrypt(nonce, data_keys[tenant_id], None)
            await conn.execute(text("INSERT INTO public.tenant_keys (id,tenant_id,encrypted_key,key_version) VALUES (:id,:tenant,:wrapped,1)"), params)
    async with elevated.begin() as conn:
        await conn.execute(text("ALTER TABLE public.whatsapp_status_events ENABLE ROW LEVEL SECURITY"))
    async with elevated.connect() as conn:
        raw = await conn.get_raw_connection()
        with pytest.raises(asyncpg.PostgresError, match="existing row policy requires review"):
            await raw.driver_connection.execute(script)
        await raw.driver_connection.execute("ROLLBACK")
    async with elevated.begin() as conn:
        assert not await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cri_rls_fixture')"))
        await conn.execute(text("ALTER TABLE public.whatsapp_status_events DISABLE ROW LEVEL SECURITY"))
    async with elevated.connect() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(script)
    async with elevated.begin() as conn:
        for role in ("fixture_rls_a", "fixture_rls_b", "fixture_rls_unbound"):
            await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'synthetic-fixture-password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"))
            await conn.execute(text(f"GRANT cri_rls_fixture TO {role}"))
        await conn.execute(text("INSERT INTO rls_rehearsal.login_tenants (login_name,tenant_id) VALUES ('fixture_rls_a',:a),('fixture_rls_b',:b)"), {"a": tenant_a, "b": tenant_b})
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO cri_rls_fixture"))
        await conn.execute(text("GRANT SELECT ON public.tenants TO cri_rls_fixture"))
        for table in TABLES:
            await conn.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO cri_rls_fixture"))
    engines = [create_async_engine(make_url(URL).set(username=role, password="synthetic-fixture-password"))
               for role in ("fixture_rls_a", "fixture_rls_b", "fixture_rls_unbound")]
    try:
        for engine, own, foreign_slug in (
            (engines[0], tenant_a, "fixture_rls_b"),
            (engines[1], tenant_b, "fixture_rls_a"),
        ):
            cache = AsyncMock()
            cache.get.return_value = data_keys[tenant_b if own == tenant_a else tenant_a].hex()
            kms = KMSService(async_sessionmaker(engine, expire_on_commit=False), cache, master_key.hex())
            own_slug = "fixture_rls_a" if own == tenant_a else "fixture_rls_b"
            assert await kms._get_data_key(own_slug) == data_keys[own]
            with pytest.raises(CRIDecryptionError, match="No active encryption key"):
                await kms._get_data_key(foreign_slug)
            cache.get.assert_not_awaited()
            cache.set.assert_not_awaited()
        for engine, own, other in ((engines[0], tenant_a, tenant_b), (engines[1], tenant_b, tenant_a)):
            async with engine.begin() as conn:
                await conn.execute(text("SELECT set_config('app.tenant_id', :other, true)"), {"other": str(other)})
                for table in TABLES:
                    rows = (await conn.execute(text(f"SELECT tenant_id FROM public.{table}"))).scalars().all()
                    assert rows == [own]
                    result = await conn.execute(text(f"UPDATE public.{table} SET tenant_id=tenant_id WHERE tenant_id=:other"), {"other": other})
                    assert result.rowcount == 0
                    result = await conn.execute(text(f"DELETE FROM public.{table} WHERE tenant_id=:other"), {"other": other})
                    assert result.rowcount == 0
                await conn.execute(text("SET LOCAL ROLE cri_rls_fixture"))
                assert (await conn.scalar(text("SELECT count(*) FROM public.whatsapp_status_events"))) == 1
            for table in TABLES:
                with pytest.raises(DBAPIError) as denied:
                    async with engine.begin() as conn:
                        await conn.execute(text(f"UPDATE public.{table} SET tenant_id=:other WHERE tenant_id=:own"), {"other": other, "own": own})
                assert denied.value.orig.sqlstate == "42501"
            with pytest.raises(DBAPIError):
                async with engine.begin() as conn:
                    await conn.execute(text("INSERT INTO public.whatsapp_status_events (tenant_id,phone_number_id,fingerprint,ciphertext,key_version) VALUES (:other,'123',repeat('e',64),'fixture',1)"), {"other": other})
            with pytest.raises(DBAPIError):
                async with engine.begin() as conn:
                    await conn.execute(text("UPDATE rls_rehearsal.login_tenants SET tenant_id=:other"), {"other": other})
        async with engines[2].connect() as conn:
            for table in TABLES:
                assert (await conn.scalar(text(f"SELECT count(*) FROM public.{table}"))) == 0
        with pytest.raises(DBAPIError):
            async with engines[2].begin() as conn:
                await conn.execute(text("INSERT INTO public.whatsapp_status_events (tenant_id,phone_number_id,fingerprint,ciphertext,key_version) VALUES (:tenant,'123',repeat('f',64),'fixture',1)"), {"tenant": tenant_a})
    finally:
        for engine in engines:
            await engine.dispose()
        async with elevated.begin() as conn:
            for table in TABLES:
                await conn.execute(text(f"DROP POLICY tenant_scope ON public.{table}"))
                await conn.execute(text(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY"))
                await conn.execute(text(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY"))
                await conn.execute(text(f"DELETE FROM public.{table} WHERE tenant_id IN (:a,:b)"), {"a": tenant_a, "b": tenant_b})
            await conn.execute(text("DROP SCHEMA rls_rehearsal CASCADE"))
            await conn.execute(text("DELETE FROM public.tenants WHERE id IN (:a,:b)"), {"a": tenant_a, "b": tenant_b})
            for role in ("fixture_rls_a", "fixture_rls_b", "fixture_rls_unbound", "cri_rls_fixture"):
                await conn.execute(text(f"DROP OWNED BY {role}"))
                await conn.execute(text(f"DROP ROLE {role}"))
        await elevated.dispose()
