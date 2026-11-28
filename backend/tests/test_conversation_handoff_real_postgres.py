"""Conversation creation and handoff behavior on disposable PostgreSQL."""
import asyncio
import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.models.enums import ConversationStatus
from app.services.conversation.service import ConversationService

URL = os.getenv("TEST_TENANT_POOL_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_concurrent_creation_and_resuming_open_handoff():
    engine = create_async_engine(URL, pool_size=10, max_overflow=0)
    tenant = TenantContext(uuid.uuid4(), "fixturehandoff", "Fixture", "active", None)
    first, second, handoff, newer = (uuid.uuid4() for _ in range(4))
    try:
        async with engine.begin() as conn:
            assert (await conn.scalar(text("SELECT current_database()"))).startswith("ragtest_")
            await conn.execute(text("CREATE SCHEMA tenant_fixturehandoff"))
            for table in ("contacts", "conversations", "messages"):
                await conn.execute(text(f"CREATE TABLE tenant_fixturehandoff.{table} "
                                        f"(LIKE tenant_template.{table} INCLUDING ALL)"))
            await conn.execute(text("INSERT INTO tenant_fixturehandoff.contacts (id,phone) VALUES "
                                    "(:first,'+212600000011'),(:second,'+212600000012')"),
                               {"first": first, "second": second})
            await conn.execute(text("INSERT INTO tenant_fixturehandoff.conversations "
                                    "(id,contact_id,status,started_at) VALUES "
                                    "(:handoff,:contact,'escalated',now()-interval '2 days'),"
                                    "(:newer,:contact,'active',now())"),
                               {"handoff": handoff, "newer": newer, "contact": second})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = ConversationService()
        with patch("app.core.tenant.get_session_factory", return_value=factory):
            conversations = await asyncio.gather(*(service.get_or_create(tenant, first) for _ in range(8)))
            assert len({row.id for row in conversations}) == 1
            existing = await service.get_or_create(tenant, second, resume_escalated=True)
            assert existing.id == handoff
            assert existing.status == ConversationStatus.escalated
            assert await service.get_status(tenant, handoff) == ConversationStatus.escalated
            assert (await service.get_or_create(tenant, second)).id == newer
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE tenant_fixturehandoff.conversations "
                                        "SET status='human_handled' WHERE id=:id"), {"id": handoff})
            assigned = await service.get_or_create(tenant, second, resume_escalated=True)
            assert assigned.id == handoff
            assert assigned.status == ConversationStatus.human_handled
            assert await service.get_status(tenant, handoff) == ConversationStatus.human_handled
        async with engine.begin() as conn:
            count = await conn.scalar(text("SELECT count(*) FROM tenant_fixturehandoff.conversations "
                                           "WHERE contact_id=:contact"), {"contact": first})
            assert count == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS tenant_fixturehandoff CASCADE"))
        await engine.dispose()
