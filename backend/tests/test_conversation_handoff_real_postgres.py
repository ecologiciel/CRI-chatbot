"""Conversation creation and handoff behavior on disposable PostgreSQL."""
import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.models.conversation import Conversation
from app.models.enums import ConversationStatus, EscalationTrigger
from app.services.conversation.service import ConversationService
from app.services.escalation.service import EscalationService
from app.services.orchestrator.faq_agent import FAQAgent
from app.services.orchestrator.graph import check_auto_escalation

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
            for table in ("contacts", "conversations", "messages", "escalations"):
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
            conversation_id = conversations[0].id
            entered, release = asyncio.Event(), asyncio.Event()

            async def send_with_lock():
                async with service.guard_bot_reply(tenant, conversation_id) as allowed:
                    assert allowed is True
                    entered.set()
                    await release.wait()

            async def take_over():
                async with tenant.db_session() as session:
                    await session.execute(update(Conversation).where(
                        Conversation.id == conversation_id
                    ).values(status=ConversationStatus.human_handled))

            sending = asyncio.create_task(send_with_lock())
            await asyncio.wait_for(entered.wait(), timeout=5)
            takeover = asyncio.create_task(take_over())
            try:
                done, _ = await asyncio.wait({takeover}, timeout=0.2)
                assert not done  # takeover cannot commit during the provider call
            finally:
                release.set()
                await asyncio.gather(sending, takeover)
            async with service.guard_bot_reply(tenant, conversation_id) as allowed:
                assert allowed is False
            async with tenant.db_session() as session:
                await session.execute(update(Conversation).where(
                    Conversation.id == conversation_id
                ).values(status=ConversationStatus.active))

            # A contact update cannot commit during a bot send. Once STOP has
            # committed, no new automatic send is allowed for that contact.
            entered, release = asyncio.Event(), asyncio.Event()
            sending = asyncio.create_task(send_with_lock())
            await asyncio.wait_for(entered.wait(), timeout=5)

            async def opt_out():
                async with engine.begin() as conn:
                    await conn.execute(text("UPDATE tenant_fixturehandoff.contacts "
                                            "SET opt_in_status='opted_out' WHERE id=:id"), {"id": first})

            stopping = asyncio.create_task(opt_out())
            try:
                done, _ = await asyncio.wait({stopping}, timeout=0.2)
                assert not done
            finally:
                release.set()
                await asyncio.gather(sending, stopping)
            async with service.guard_bot_reply(tenant, conversation_id) as allowed:
                assert allowed is False
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE tenant_fixturehandoff.contacts SET opt_in_status='pending' WHERE id=:id"), {"id": first})
                # A busy contact fails closed quickly without a lock-order
                # deadlock; the transaction remains usable after NOWAIT.
                async with service.guard_bot_reply(tenant, conversation_id) as allowed:
                    assert allowed is False
            async with service.guard_bot_reply(tenant, conversation_id) as allowed:
                assert allowed is True
            retrieval = AsyncMock()
            retrieval.retrieve.return_value = MagicMock(chunks=[])
            faq = FAQAgent(retrieval, AsyncMock())
            state = {"conversation_id": str(conversation_id), "query": "fixture", "language": "fr"}
            with patch("app.services.orchestrator.faq_agent.get_conversation_service", return_value=service):
                first_turn = await faq.handle(state, tenant)
                second_turn = await faq.handle(state, tenant)
            assert first_turn["consecutive_low_confidence"] == 1
            assert check_auto_escalation(second_turn) == "escalation_handler"
            assert await service.record_faq_outcome(tenant, conversation_id, low_confidence=False) == 0
            counters = await asyncio.gather(*(
                service.record_faq_outcome(tenant, conversation_id, low_confidence=True)
                for _ in range(8)
            ))
            assert counters.count(1) == 1 and counters.count(2) == 7
            assert await service.record_faq_outcome(tenant, conversation_id, low_confidence=False) == 0
            assert await service.record_faq_outcome(tenant, conversation_id, low_confidence=True) == 1
            await asyncio.gather(
                service.record_faq_outcome(tenant, conversation_id, low_confidence=True),
                service.update_metadata(tenant, conversation_id, {"other": "preserved"}),
            )
            async with tenant.db_session() as session:
                metadata = (await session.execute(text(
                    "SELECT metadata FROM conversations WHERE id=:id"
                ), {"id": conversation_id})).scalar_one()
            assert metadata["rag_low_confidence_count"] == 2
            assert metadata["other"] == "preserved"

            escalation_service = EscalationService(AsyncMock(), AsyncMock(), AsyncMock())
            escalation_service.generate_context_summary = AsyncMock(return_value=None)
            with patch("app.services.escalation.service.get_redis", return_value=AsyncMock()):
                escalations = await asyncio.gather(*(
                    escalation_service.create_escalation(
                        conversation_id, EscalationTrigger.rag_failure, None, tenant
                    ) for _ in range(8)
                ))
                assert len({item.id for item in escalations}) == 1
                assert await service.record_faq_outcome(tenant, conversation_id, low_confidence=True) is None
                async with service.guard_bot_reply(tenant, conversation_id, escalations[0].id) as allowed:
                    assert allowed is True
                async with service.guard_bot_reply(tenant, conversation_id, uuid.uuid4()) as allowed:
                    assert allowed is False
                await escalation_service.close_escalation(
                    escalations[0].id, "fixture", uuid.uuid4(), tenant
                )
            assert await service.record_faq_outcome(tenant, conversation_id, low_confidence=True) == 1
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
