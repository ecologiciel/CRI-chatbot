"""Exercise the agent-reply lifecycle as a restricted role on a disposable schema."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.crypto.kms import KMSService
from app.services.crypto.versioned_envelope import VersionedEnvelopeService
from app.services.escalation.reply_leases import claim_next_reply, quarantine_reply
from app.services.escalation.reply_outbox import register_agent_reply
from app.services.escalation.reply_retention import redact_tenant_replies
from app.services.escalation.reply_review import review_agent_reply
from app.services.tenant.provisioning import TenantProvisioningService

URL = os.getenv("TEST_WA_FENCE_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest.mark.asyncio
async def test_restricted_role_can_run_reply_lifecycle_but_cannot_erase_fences():
    elevated = create_async_engine(URL)
    admin_factory = async_sessionmaker(elevated, expire_on_commit=False)
    tenant_id, actor_id, contact_id, conversation_id, escalation_id = (uuid.uuid4() for _ in range(5))
    tenant = TenantContext(tenant_id, "fixture_runtime_reply", "Fixture", "active", None)
    async with elevated.begin() as conn:
        assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
        assert not await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cri_runtime_access')"))
        await conn.execute(text("INSERT INTO public.tenants (id,name,slug,region,status,whatsapp_config) VALUES (:id,'Fixture','fixture_runtime_reply','Test','active','{\"phone_number_id\":\"981\",\"access_token\":\"fixture\"}')"), {"id": tenant_id})
        await conn.execute(text("INSERT INTO public.admins (id,email,password_hash,full_name,role,tenant_id) VALUES (:id,'runtime-reply@example.test','fixture','Fixture','admin_tenant',:tenant)"), {"id": actor_id, "tenant": tenant_id})
    with patch("app.services.tenant.provisioning.get_session_factory", return_value=admin_factory):
        await TenantProvisioningService()._create_schema(tenant.slug)
    async with elevated.begin() as conn:
        await conn.execute(text("INSERT INTO tenant_fixture_runtime_reply.contacts (id,phone,opt_in_status) VALUES (:id,'+212600000076','opted_in')"), {"id": contact_id})
        await conn.execute(text("INSERT INTO tenant_fixture_runtime_reply.conversations (id,contact_id,status) VALUES (:id,:contact,'human_handled')"), {"id": conversation_id, "contact": contact_id})
        await conn.execute(text("INSERT INTO tenant_fixture_runtime_reply.escalations (id,conversation_id,trigger_type,priority,status) VALUES (:id,:conversation,'manual','medium','assigned')"), {"id": escalation_id, "conversation": conversation_id})
    await KMSService(admin_factory, AsyncMock(), "08" * 32).generate_tenant_key(tenant_id)
    scripts = Path(__file__).parents[2] / "scripts"
    prepare = (scripts / "prepare-runtime-db-role.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
    refresh = (scripts / "rehearse-refresh-runtime-grants.sql").read_text().replace("\\set ON_ERROR_STOP on", "")
    prepare = prepare.replace("\\ir rehearse-refresh-runtime-grants.sql", refresh)
    async with elevated.connect() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(prepare)

    restricted = create_async_engine(URL)

    @event.listens_for(restricted.sync_engine, "connect")
    def set_restricted_role(connection, _record):
        cursor = connection.cursor()
        cursor.execute("SET ROLE cri_runtime_access")
        cursor.close()

    factory = async_sessionmaker(restricted, expire_on_commit=False)
    cipher = VersionedEnvelopeService(factory, "08" * 32)
    try:
        with (patch("app.services.escalation.reply_outbox.get_session_factory", return_value=factory),
              patch("app.services.escalation.reply_review.get_session_factory", return_value=factory),
              patch("app.services.escalation.reply_retention.get_session_factory", return_value=factory)):
            registered = await register_agent_reply(tenant, escalation_id, actor_id, uuid.uuid4(), "synthetic reply", cipher=cipher)
            async with factory() as session:
                claim = await claim_next_reply(session)
                assert claim and claim.id == registered.id
                await session.commit()
            async with factory() as session:
                await quarantine_reply(session, claim)
                await session.commit()
            assert await review_agent_reply(tenant, escalation_id, registered.id, actor_id, action="resolve", decision="unknown_no_retry") == "resolved"
            counts = await redact_tenant_replies(tenant_id, tenant.slug, 90, datetime.now(UTC) + timedelta(days=91))
            assert counts == {"redacted": 1, "overdue_unresolved": 0}
        for statement in ("DELETE FROM public.agent_reply_outbox_events", "TRUNCATE public.agent_reply_outbox_events", "UPDATE public.agent_reply_outbox_events SET request_key=gen_random_uuid()", "UPDATE public.audit_logs SET action='fixture'"):
            with pytest.raises(DBAPIError):
                async with factory() as session:
                    await session.execute(text(statement))
                    await session.commit()
    finally:
        await restricted.dispose()
        async with elevated.begin() as conn:
            await conn.execute(text("DELETE FROM public.agent_reply_outbox_events WHERE tenant_id=:id"), {"id": tenant_id})
            await conn.execute(text("DROP SCHEMA tenant_fixture_runtime_reply CASCADE"))
            await conn.execute(text("DELETE FROM public.admins WHERE id=:id"), {"id": actor_id})
            await conn.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant_id})
            await conn.execute(text("DROP OWNED BY cri_runtime_access"))
            await conn.execute(text("DROP ROLE cri_runtime_access"))
        await elevated.dispose()
