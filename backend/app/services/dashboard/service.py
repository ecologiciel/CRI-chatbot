"""DashboardService — aggregated KPIs for the back-office dashboard.

Runs all aggregate queries within a single tenant DB session for efficiency.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select

from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.enums import (
    ConversationStatus,
    FeedbackRating,
    KBDocumentStatus,
    UnansweredStatus,
)
from app.models.feedback import Feedback, UnansweredQuestion
from app.models.kb import KBDocument

logger = structlog.get_logger()


class DashboardService:
    """Compute aggregated dashboard statistics for a tenant."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="dashboard_service")

    async def get_stats(self, tenant: TenantContext) -> dict:
        """Get all dashboard KPIs in a single DB session.

        Returns:
            Dict matching DashboardStatsResponse fields.
        """
        async with tenant.db_session() as session:
            # 1. Active conversations
            active_result = await session.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.status == ConversationStatus.active,
                ),
            )
            active_conversations = active_result.scalar_one()

            # 2. Messages today
            today_start = datetime.now(UTC).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            msg_result = await session.execute(
                select(func.count(Message.id)).where(
                    Message.timestamp >= today_start,
                ),
            )
            messages_today = msg_result.scalar_one()

            # 3. Total contacts
            contacts_result = await session.execute(
                select(func.count(Contact.id)),
            )
            total_contacts = contacts_result.scalar_one()

            # 4. KB documents indexed
            kb_result = await session.execute(
                select(func.count(KBDocument.id)).where(
                    KBDocument.status == KBDocumentStatus.indexed,
                ),
            )
            kb_documents_indexed = kb_result.scalar_one()

            # 5. Unanswered questions (pending)
            uq_result = await session.execute(
                select(func.count(UnansweredQuestion.id)).where(
                    UnansweredQuestion.status == UnansweredStatus.pending,
                ),
            )
            unanswered_questions = uq_result.scalar_one()

            # 6. Resolution rate (last 30 days)
            resolution_result = await session.execute(
                select(
                    Conversation.status,
                    func.count(Conversation.id).label("cnt"),
                ).group_by(Conversation.status),
            )
            status_counts = {row[0]: row[1] for row in resolution_result.all()}
            ended = status_counts.get(ConversationStatus.ended, 0)
            total_conv = sum(status_counts.values())
            resolution_rate = round((ended / total_conv * 100), 1) if total_conv > 0 else 0.0

            # 7. CSAT score
            feedback_result = await session.execute(
                select(
                    Feedback.rating,
                    func.count().label("cnt"),
                ).group_by(Feedback.rating),
            )
            feedback_counts = {row[0]: row[1] for row in feedback_result.all()}
            positive = feedback_counts.get(FeedbackRating.positive, 0)
            negative = feedback_counts.get(FeedbackRating.negative, 0)
            denominator = positive + negative
            satisfaction_rate = positive / denominator if denominator > 0 else 0.0
            csat_score = round(satisfaction_rate * 5, 1)

        return {
            "active_conversations": active_conversations,
            "messages_today": messages_today,
            "resolution_rate": resolution_rate,
            "csat_score": csat_score,
            "total_contacts": total_contacts,
            "kb_documents_indexed": kb_documents_indexed,
            "unanswered_questions": unanswered_questions,
            "quota_usage": None,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_dashboard_service: DashboardService | None = None


def get_dashboard_service() -> DashboardService:
    """Get or create the DashboardService singleton."""
    global _dashboard_service  # noqa: PLW0603
    if _dashboard_service is None:
        _dashboard_service = DashboardService()
    return _dashboard_service
