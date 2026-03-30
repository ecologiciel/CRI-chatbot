"""Tests for FeedbackService — feedback collection and unanswered question management."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.enums import (
    FeedbackRating,
    MessageDirection,
    UnansweredStatus,
)
from app.models.feedback import Feedback, UnansweredQuestion
from app.schemas.feedback import FeedbackCreate, UnansweredQuestionUpdate
from app.services.feedback.service import FeedbackService

# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_message(
    *,
    message_id=None,
    conversation_id=None,
    direction=MessageDirection.outbound,
    content="Réponse du bot",
    chunk_ids=None,
    timestamp=None,
    metadata_=None,
):
    """Create a mock Message object."""
    msg = MagicMock()
    msg.id = message_id or uuid.uuid4()
    msg.conversation_id = conversation_id or uuid.uuid4()
    msg.direction = direction
    msg.content = content
    msg.chunk_ids = chunk_ids if chunk_ids is not None else ["chunk_1", "chunk_2"]
    msg.timestamp = timestamp or datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC)
    msg.metadata_ = metadata_ or {"language": "fr"}
    return msg


def _make_feedback_create(message_id=None, rating=FeedbackRating.positive):
    """Create a FeedbackCreate schema."""
    return FeedbackCreate(
        message_id=message_id or uuid.uuid4(),
        rating=rating,
        reason=None,
        comment=None,
    )


def _mock_session():
    """Create a mock async DB session with context manager support."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# --- Tests ---


class TestCreateFeedback:
    """Tests for FeedbackService.create_feedback."""

    @pytest.mark.asyncio
    async def test_create_positive_feedback(self):
        """Positive feedback → Feedback created, no UnansweredQuestion."""
        message = _make_message(chunk_ids=["c1", "c2"])
        data = _make_feedback_create(message_id=message.id, rating=FeedbackRating.positive)

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = message
        session.execute = AsyncMock(return_value=mock_result)

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            feedback = await svc.create_feedback(TEST_TENANT, data)

        assert isinstance(feedback, Feedback)
        assert feedback.message_id == message.id
        assert feedback.rating == FeedbackRating.positive
        assert feedback.chunk_ids == ["c1", "c2"]
        # session.add called once (Feedback only, no UnansweredQuestion)
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_feedback_auto_populates_chunk_ids(self):
        """chunk_ids come from the Message, not from the caller."""
        message = _make_message(chunk_ids=["auto_chunk_1", "auto_chunk_3"])
        data = _make_feedback_create(message_id=message.id)

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = message
        session.execute = AsyncMock(return_value=mock_result)

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            feedback = await svc.create_feedback(TEST_TENANT, data)

        assert feedback.chunk_ids == ["auto_chunk_1", "auto_chunk_3"]

    @pytest.mark.asyncio
    async def test_create_feedback_message_not_found(self):
        """Non-existent message_id → ResourceNotFoundError."""
        data = _make_feedback_create()

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        svc = FeedbackService()
        with (
            patch.object(TenantContext, "db_session", return_value=session),
            pytest.raises(ResourceNotFoundError),
        ):
            await svc.create_feedback(TEST_TENANT, data)

    @pytest.mark.asyncio
    async def test_create_negative_feedback_creates_unanswered(self):
        """Negative feedback → UnansweredQuestion created."""
        conv_id = uuid.uuid4()
        outbound_msg = _make_message(
            conversation_id=conv_id,
            direction=MessageDirection.outbound,
            timestamp=datetime(2026, 3, 26, 12, 1, 0, tzinfo=UTC),
        )
        inbound_msg = _make_message(
            conversation_id=conv_id,
            direction=MessageDirection.inbound,
            content="Comment créer une SARL ?",
            timestamp=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
        )
        data = _make_feedback_create(
            message_id=outbound_msg.id,
            rating=FeedbackRating.negative,
        )

        session = _mock_session()

        # First execute: fetch the rated message
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = outbound_msg

        # Second execute (flush): no-op
        # Third execute: find user's inbound question
        user_msg_result = MagicMock()
        user_msg_result.scalar_one_or_none.return_value = inbound_msg

        # Fourth execute: check existing UnansweredQuestion (none found)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(
            side_effect=[msg_result, user_msg_result, existing_result],
        )

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.flush = AsyncMock()

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            await svc.create_feedback(TEST_TENANT, data)

        # Should have added Feedback + UnansweredQuestion
        assert len(added_objects) == 2
        feedback_obj = added_objects[0]
        uq_obj = added_objects[1]

        assert isinstance(feedback_obj, Feedback)
        assert isinstance(uq_obj, UnansweredQuestion)
        assert uq_obj.question == "Comment créer une SARL ?"
        assert uq_obj.frequency == 1
        assert uq_obj.status == UnansweredStatus.pending
        assert uq_obj.source_conversation_id == conv_id

    @pytest.mark.asyncio
    async def test_negative_feedback_increments_frequency(self):
        """Same question flagged twice → frequency incremented."""
        conv_id = uuid.uuid4()
        outbound_msg = _make_message(
            conversation_id=conv_id,
            timestamp=datetime(2026, 3, 26, 12, 1, 0, tzinfo=UTC),
        )
        inbound_msg = _make_message(
            conversation_id=conv_id,
            direction=MessageDirection.inbound,
            content="Question déjà flaggée",
            timestamp=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
        )
        existing_uq = MagicMock(spec=UnansweredQuestion)
        existing_uq.frequency = 1

        data = _make_feedback_create(
            message_id=outbound_msg.id,
            rating=FeedbackRating.negative,
        )

        session = _mock_session()

        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = outbound_msg

        user_msg_result = MagicMock()
        user_msg_result.scalar_one_or_none.return_value = inbound_msg

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_uq

        session.execute = AsyncMock(
            side_effect=[msg_result, user_msg_result, existing_result],
        )
        session.flush = AsyncMock()

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            await svc.create_feedback(TEST_TENANT, data)

        assert existing_uq.frequency == 2


class TestFeedbackStats:
    """Tests for FeedbackService.get_feedback_stats."""

    @pytest.mark.asyncio
    async def test_get_feedback_stats(self):
        """Stats computed correctly from aggregate counts."""
        session = _mock_session()

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (FeedbackRating.positive, 7),
            (FeedbackRating.negative, 2),
            (FeedbackRating.question, 1),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            stats = await svc.get_feedback_stats(TEST_TENANT)

        assert stats["total"] == 10
        assert stats["positive"] == 7
        assert stats["negative"] == 2
        assert stats["question"] == 1
        assert stats["satisfaction_rate"] == pytest.approx(7 / 9, abs=0.001)

    @pytest.mark.asyncio
    async def test_get_feedback_stats_no_data(self):
        """No feedback → all zeros, satisfaction_rate 0.0."""
        session = _mock_session()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            stats = await svc.get_feedback_stats(TEST_TENANT)

        assert stats["total"] == 0
        assert stats["satisfaction_rate"] == 0.0


class TestListUnansweredQuestions:
    """Tests for FeedbackService.list_unanswered_questions."""

    @pytest.mark.asyncio
    async def test_list_unanswered_ordered_by_frequency(self):
        """Questions returned ordered by frequency DESC."""
        q1 = MagicMock(spec=UnansweredQuestion, frequency=5)
        q2 = MagicMock(spec=UnansweredQuestion, frequency=10)

        session = _mock_session()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [q2, q1]  # frequency DESC
        data_result.scalars.return_value = mock_scalars

        session.execute = AsyncMock(side_effect=[count_result, data_result])

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            items, total = await svc.list_unanswered_questions(TEST_TENANT)

        assert total == 2
        assert items[0].frequency == 10
        assert items[1].frequency == 5


class TestUpdateUnansweredQuestion:
    """Tests for FeedbackService.update_unanswered_question."""

    @pytest.mark.asyncio
    async def test_update_unanswered_question_success(self):
        """Update status and proposed_answer, set reviewed_by."""
        question_id = uuid.uuid4()
        admin_id = uuid.uuid4()

        existing = MagicMock(spec=UnansweredQuestion)
        existing.id = question_id
        existing.status = UnansweredStatus.pending

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=mock_result)

        data = UnansweredQuestionUpdate(
            status=UnansweredStatus.approved,
            proposed_answer="La SARL nécessite un capital minimum de 1 MAD.",
        )

        svc = FeedbackService()
        with patch.object(TenantContext, "db_session", return_value=session):
            result = await svc.update_unanswered_question(
                TEST_TENANT,
                question_id,
                data,
                admin_id,
            )

        assert result.status == UnansweredStatus.approved
        assert result.proposed_answer == "La SARL nécessite un capital minimum de 1 MAD."
        assert result.reviewed_by == admin_id

    @pytest.mark.asyncio
    async def test_update_unanswered_question_not_found(self):
        """Non-existent question_id → ResourceNotFoundError."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        data = UnansweredQuestionUpdate(status=UnansweredStatus.rejected)

        svc = FeedbackService()
        with (
            patch.object(TenantContext, "db_session", return_value=session),
            pytest.raises(ResourceNotFoundError),
        ):
            await svc.update_unanswered_question(
                TEST_TENANT,
                uuid.uuid4(),
                data,
                uuid.uuid4(),
            )
