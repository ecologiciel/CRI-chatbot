"""A response without confirmed provider acceptance must not enter chat context."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import MessageDirection
from app.schemas.conversation import MessageResponse
from app.services.conversation.service import ConversationService


@pytest.mark.asyncio
async def test_unconfirmed_outbound_is_not_used_for_history_or_sources():
    failed = SimpleNamespace(
        direction=MessageDirection.outbound,
        content="Réponse non confirmée",
        metadata_={"delivery_state": "unconfirmed", "sources": [{"title": "Non confirmée"}]},
    )
    earlier = SimpleNamespace(
        direction=MessageDirection.outbound,
        content="Réponse antérieure",
        metadata_={"sources": [{"title": "Confirmée"}]},
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [failed, earlier]
    result.scalars.return_value.__iter__.return_value = iter([failed, earlier])
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def db_session():
        yield session

    tenant = SimpleNamespace(db_session=db_session)
    service = ConversationService()
    conversation_id = uuid.uuid4()
    history = await service.get_history(tenant, conversation_id)
    assert history == [{"role": "assistant", "content": "Réponse antérieure"}]
    assert await service.get_latest_sources(tenant, conversation_id) == [{"title": "Confirmée"}]


@pytest.mark.parametrize(
    "metadata,expected", [({"delivery_state": "unconfirmed"}, "unconfirmed"), (None, None)]
)
def test_message_response_exposes_delivery_state_without_all_metadata(metadata, expected):
    message = SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        direction="outbound",
        type="text",
        content="Test",
        media_url=None,
        chunk_ids=[],
        whatsapp_message_id=None,
        metadata_=metadata,
        timestamp=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    serialized = MessageResponse.model_validate(message).model_dump()
    assert serialized["delivery_state"] == expected
    assert "metadata_" not in serialized


def test_message_response_exposes_delivery_review_without_other_metadata():
    message = SimpleNamespace(
        id=uuid.uuid4(), conversation_id=uuid.uuid4(), direction="outbound", type="text",
        content="Test", media_url=None, chunk_ids=[], whatsapp_message_id="fixture",
        metadata_={"delivery_state": "delivered", "delivery_review_required": True,
                   "private_fixture": "not disclosed"},
        timestamp=datetime.now(UTC), created_at=datetime.now(UTC),
    )
    serialized = MessageResponse.model_validate(message).model_dump()
    assert serialized["delivery_state"] == "delivered"
    assert serialized["delivery_review_required"] is True
    assert "private_fixture" not in str(serialized)
