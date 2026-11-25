"""Exercise conversation supervision against isolated tenant schemas in PostgreSQL."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.conversations import (
    _supervision,
    get_conversation,
    list_conversations,
    list_messages,
)
from app.core.exceptions import AuthorizationError
from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import ContactSource, MessageDirection, MessageType
from app.schemas.auth import AdminTokenPayload


@pytest.mark.asyncio
async def test_viewer_cannot_supervise_conversations():
    viewer = AdminTokenPayload(
        sub=str(uuid.uuid4()), role="viewer", exp=100, iat=0, jti="test", type="access"
    )
    with pytest.raises(AuthorizationError):
        await _supervision(viewer)


@pytest.mark.asyncio
async def test_tenant_scoped_conversation_supervision():
    dsn = os.environ.get("CONVERSATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set CONVERSATION_TEST_DSN to a disposable conversation_test database")
    engine = create_async_engine(dsn)
    suffix = uuid.uuid4().hex[:10]
    tenant_a = TenantContext(
        id=uuid.uuid4(), slug=f"conva{suffix}", name="A", status="active", whatsapp_config=None
    )
    tenant_b = TenantContext(
        id=uuid.uuid4(), slug=f"convb{suffix}", name="B", status="active", whatsapp_config=None
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created = []
    try:
        async with engine.begin() as connection:
            assert (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one() == "conversation_test"
            for schema in (tenant_a.db_schema, tenant_b.db_schema):
                assert (
                    await connection.execute(
                        text("SELECT to_regnamespace(:schema) IS NULL"), {"schema": schema}
                    )
                ).scalar_one()
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                created.append(schema)
                await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
                for table in (Contact.__table__, Conversation.__table__, Message.__table__):
                    await connection.run_sync(lambda conn, t=table: t.create(conn, checkfirst=True))
        with patch("app.core.tenant.get_session_factory", return_value=factory):
            async with tenant_a.db_session() as session:
                contact = Contact(phone="web-test", source=ContactSource.web)
                session.add(contact)
                await session.flush()
                conversation = Conversation(contact_id=contact.id)
                session.add(conversation)
                await session.flush()
                conversation_id = conversation.id
                now = datetime.now(UTC)
                session.add_all(
                    [
                        Message(
                            conversation_id=conversation.id,
                            direction=MessageDirection.inbound,
                            type=MessageType.text,
                            content="Question réelle",
                            timestamp=now,
                        ),
                        Message(
                            conversation_id=conversation.id,
                            direction=MessageDirection.outbound,
                            type=MessageType.text,
                            content="Réponse réelle",
                            timestamp=now + timedelta(seconds=1),
                        ),
                    ]
                )

            result = await list_conversations(tenant_a, None, page=1, page_size=20, search=None)
            assert result.total == 1
            assert result.items[0].contact_phone is None
            assert result.items[0].channel == "web"
            assert result.items[0].last_message == "Réponse réelle"
            assert (
                await list_conversations(tenant_a, None, page=1, page_size=20, search="absent")
            ).total == 0
            messages = await list_messages(conversation_id, tenant_a, None, page=1, page_size=1)
            assert messages.total == 2 and len(messages.items) == 1
            assert (await get_conversation(conversation_id, tenant_a, None)).id == conversation_id
            assert (
                await list_conversations(tenant_b, None, page=1, page_size=20, search=None)
            ).total == 0
            with pytest.raises(HTTPException) as exc:
                await list_messages(conversation_id, tenant_b, None, page=1, page_size=20)
            assert exc.value.status_code == 404
            with pytest.raises(HTTPException) as exc:
                await get_conversation(conversation_id, tenant_b, None)
            assert exc.value.status_code == 404
    finally:
        if created:
            async with engine.begin() as connection:
                for schema in created:
                    await connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()
