"""Unit tests for FeedbackService — create feedback, stats, unanswered questions."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.enums import FeedbackRating
from app.schemas.feedback import FeedbackCreate
from app.services.feedback.service import FeedbackService


def _make_message_orm(chunk_ids=None, conversation_id=None):
    """Create a mock Message ORM object."""
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.conversation_id = conversation_id or uuid.uuid4()
    msg.direction = "outbound"
    msg.chunk_ids = chunk_ids or ["chunk-1", "chunk-2"]
    msg.content = "Test response"
    msg.timestamp = MagicMock()
    msg.metadata_ = {"language": "fr"}
    return msg


def _make_db_session_patch(mock_session):
    """Create a class-level patch for TenantContext.db_session accepting self."""

    @asynccontextmanager
    async def _fake_db(self_arg):
        yield mock_session

    return patch.object(TenantContext, "db_session", _fake_db)


class TestCreatePositiveFeedback:
    """Positive feedback does NOT create UnansweredQuestion."""

    @pytest.mark.asyncio
    async def test_positive_feedback_created(self, tenant_context):
        """Positive rating creates feedback, no unanswered question."""
        msg = _make_message_orm()
        session = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg
        session.execute = AsyncMock(return_value=msg_result)

        data = FeedbackCreate(message_id=msg.id, rating=FeedbackRating.positive)

        with _make_db_session_patch(session):
            service = FeedbackService()
            await service.create_feedback(tenant_context, data)

        session.add.assert_called_once()
        session.flush.assert_called_once()


class TestCreateNegativeFeedback:
    """Negative feedback creates UnansweredQuestion."""

    @pytest.mark.asyncio
    async def test_negative_creates_unanswered(self, tenant_context):
        """Negative rating triggers _flag_unanswered."""
        msg = _make_message_orm()
        session = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        # Sequence: 1) fetch message, 2) find inbound question, 3) check existing UQ
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg

        inbound_msg = MagicMock()
        inbound_msg.content = "Original question?"
        inbound_result = MagicMock()
        inbound_result.scalar_one_or_none.return_value = inbound_msg

        uq_result = MagicMock()
        uq_result.scalar_one_or_none.return_value = None  # No existing UQ

        session.execute = AsyncMock(
            side_effect=[msg_result, inbound_result, uq_result],
        )

        data = FeedbackCreate(
            message_id=msg.id,
            rating=FeedbackRating.negative,
            reason="incomplete",
        )

        with _make_db_session_patch(session):
            service = FeedbackService()
            await service.create_feedback(tenant_context, data)

        # session.add called for Feedback and UnansweredQuestion
        assert session.add.call_count >= 2


class TestMessageNotFound:
    """Non-existent message_id raises ResourceNotFoundError."""

    @pytest.mark.asyncio
    async def test_message_not_found_raises(self, tenant_context):
        """ResourceNotFoundError for non-existent message_id."""
        session = AsyncMock()
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=msg_result)

        data = FeedbackCreate(message_id=uuid.uuid4(), rating=FeedbackRating.positive)

        with _make_db_session_patch(session):
            service = FeedbackService()
            with pytest.raises(ResourceNotFoundError, match="not found"):
                await service.create_feedback(tenant_context, data)


class TestFeedbackStats:
    """Feedback statistics calculation."""

    @pytest.mark.asyncio
    async def test_stats_calculation(self, tenant_context):
        """satisfaction_rate = positive / (positive + negative)."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (FeedbackRating.positive, 80),
            (FeedbackRating.negative, 20),
            (FeedbackRating.question, 10),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        with _make_db_session_patch(session):
            service = FeedbackService()
            stats = await service.get_feedback_stats(tenant_context)

        assert stats["total"] == 110
        assert stats["positive"] == 80
        assert stats["negative"] == 20
        assert stats["satisfaction_rate"] == 0.8

    @pytest.mark.asyncio
    async def test_stats_no_data(self, tenant_context):
        """All zeros when no feedback exists."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        with _make_db_session_patch(session):
            service = FeedbackService()
            stats = await service.get_feedback_stats(tenant_context)

        assert stats["total"] == 0
        assert stats["satisfaction_rate"] == 0.0
