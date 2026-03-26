"""FeedbackService — collect ratings, correlate chunks, manage unanswered questions.

Handles:
- Creating feedback entries with auto-populated chunk_ids from the rated Message
- Auto-flagging unanswered questions on negative feedback
- Feedback statistics for the back-office dashboard
- CRUD for unanswered questions (supervised learning review)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from app.core.exceptions import ResourceNotFoundError
from app.core.tenant import TenantContext
from app.models.conversation import Message
from app.models.enums import FeedbackRating, MessageDirection, UnansweredStatus
from app.models.feedback import Feedback, UnansweredQuestion
from app.schemas.feedback import FeedbackCreate, UnansweredQuestionUpdate

logger = structlog.get_logger()


class FeedbackService:
    """Collect and process user feedback on chatbot responses."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="feedback_service")

    # ── Create feedback ──

    async def create_feedback(
        self,
        tenant: TenantContext,
        data: FeedbackCreate,
    ) -> Feedback:
        """Record a feedback entry with auto-populated chunk_ids.

        Steps:
        1. Fetch the rated Message to extract chunk_ids
        2. Create Feedback record
        3. If negative → auto-flag unanswered question

        Args:
            tenant: Tenant context for DB session.
            data: Feedback creation payload (message_id, rating, reason, comment).

        Returns:
            Created Feedback ORM object.

        Raises:
            ResourceNotFoundError: If message_id does not exist.
        """
        async with tenant.db_session() as session:
            # Fetch the rated message to get chunk_ids
            result = await session.execute(
                select(Message).where(Message.id == data.message_id),
            )
            message = result.scalar_one_or_none()
            if message is None:
                raise ResourceNotFoundError(
                    f"Message {data.message_id} not found",
                )

            # Create feedback with chunk_ids from the message
            feedback = Feedback(
                message_id=data.message_id,
                rating=data.rating,
                reason=data.reason,
                comment=data.comment,
                chunk_ids=message.chunk_ids or [],
            )
            session.add(feedback)
            await session.flush()

            # Auto-flag unanswered question for negative feedback
            if data.rating == FeedbackRating.negative:
                await self._flag_unanswered(session, message)

            self._logger.info(
                "feedback_created",
                feedback_id=str(feedback.id),
                rating=data.rating.value,
                tenant=tenant.slug,
                chunk_count=len(feedback.chunk_ids),
            )
            return feedback

    async def _flag_unanswered(
        self,
        session,
        rated_message: Message,
    ) -> None:
        """Create or increment UnansweredQuestion for negative feedback.

        Finds the user's inbound question that preceded the rated outbound
        message, then either increments an existing UnansweredQuestion or
        creates a new one.
        """
        # Find the user's question (most recent inbound before the rated message)
        result = await session.execute(
            select(Message)
            .where(
                Message.conversation_id == rated_message.conversation_id,
                Message.direction == MessageDirection.inbound,
                Message.timestamp < rated_message.timestamp,
            )
            .order_by(Message.timestamp.desc())
            .limit(1),
        )
        user_msg = result.scalar_one_or_none()
        if not user_msg or not user_msg.content:
            return

        question_text = user_msg.content

        # Check if this question is already flagged (pending or under review)
        existing_result = await session.execute(
            select(UnansweredQuestion).where(
                UnansweredQuestion.question == question_text,
                UnansweredQuestion.status.in_([
                    UnansweredStatus.pending,
                    UnansweredStatus.approved,
                    UnansweredStatus.modified,
                ]),
            ),
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.frequency += 1
        else:
            # Detect language from message metadata or default to "fr"
            metadata = rated_message.metadata_ or {}
            language = metadata.get("language", "fr")

            uq = UnansweredQuestion(
                question=question_text,
                language=language,
                frequency=1,
                status=UnansweredStatus.pending,
                source_conversation_id=rated_message.conversation_id,
            )
            session.add(uq)

    # ── Statistics ──

    async def get_feedback_stats(
        self,
        tenant: TenantContext,
    ) -> dict:
        """Get feedback statistics for the back-office dashboard.

        Returns:
            Dict with total, positive, negative, question counts
            and satisfaction_rate (0.0-1.0).
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(
                    Feedback.rating,
                    func.count().label("cnt"),
                ).group_by(Feedback.rating),
            )
            rows = result.all()

        counts = {r.value: 0 for r in FeedbackRating}
        for rating, cnt in rows:
            counts[rating.value] = cnt

        positive = counts[FeedbackRating.positive.value]
        negative = counts[FeedbackRating.negative.value]
        question = counts[FeedbackRating.question.value]
        total = positive + negative + question
        denominator = positive + negative
        satisfaction_rate = positive / denominator if denominator > 0 else 0.0

        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "question": question,
            "satisfaction_rate": round(satisfaction_rate, 4),
        }

    # ── List feedback ──

    async def list_feedback(
        self,
        tenant: TenantContext,
        *,
        page: int = 1,
        page_size: int = 20,
        rating: FeedbackRating | None = None,
    ) -> tuple[list[Feedback], int]:
        """List feedback entries with optional rating filter.

        Returns:
            Tuple of (items, total_count).
        """
        async with tenant.db_session() as session:
            base = select(Feedback)
            if rating is not None:
                base = base.where(Feedback.rating == rating)

            # Count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # Paginated data
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(Feedback.created_at.desc())
                .offset(offset)
                .limit(page_size),
            )
            items = list(data_result.scalars().all())

        return items, total

    # ── Unanswered questions ──

    async def list_unanswered_questions(
        self,
        tenant: TenantContext,
        *,
        page: int = 1,
        page_size: int = 20,
        status: UnansweredStatus | None = None,
    ) -> tuple[list[UnansweredQuestion], int]:
        """List unanswered questions ordered by frequency DESC.

        Returns:
            Tuple of (items, total_count).
        """
        async with tenant.db_session() as session:
            base = select(UnansweredQuestion)
            if status is not None:
                base = base.where(UnansweredQuestion.status == status)

            # Count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # Paginated data — most asked first
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(
                    UnansweredQuestion.frequency.desc(),
                    UnansweredQuestion.created_at.desc(),
                )
                .offset(offset)
                .limit(page_size),
            )
            items = list(data_result.scalars().all())

        return items, total

    async def update_unanswered_question(
        self,
        tenant: TenantContext,
        question_id: uuid.UUID,
        data: UnansweredQuestionUpdate,
        admin_id: uuid.UUID,
    ) -> UnansweredQuestion:
        """Review an unanswered question (approve, reject, edit).

        Args:
            tenant: Tenant context for DB session.
            question_id: UUID of the question to update.
            data: Update payload (status, proposed_answer, review_note).
            admin_id: UUID of the reviewing admin.

        Returns:
            Updated UnansweredQuestion ORM object.

        Raises:
            ResourceNotFoundError: If question_id does not exist.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(UnansweredQuestion).where(
                    UnansweredQuestion.id == question_id,
                ),
            )
            question = result.scalar_one_or_none()
            if question is None:
                raise ResourceNotFoundError(
                    f"UnansweredQuestion {question_id} not found",
                )

            # Apply non-None fields
            if data.status is not None:
                question.status = data.status
                question.reviewed_by = admin_id
            if data.proposed_answer is not None:
                question.proposed_answer = data.proposed_answer
            if data.review_note is not None:
                question.review_note = data.review_note

            self._logger.info(
                "unanswered_question_updated",
                question_id=str(question_id),
                new_status=data.status.value if data.status else None,
                tenant=tenant.slug,
                admin_id=str(admin_id),
            )
            return question


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_feedback_service: FeedbackService | None = None


def get_feedback_service() -> FeedbackService:
    """Get or create the FeedbackService singleton."""
    global _feedback_service  # noqa: PLW0603
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service
