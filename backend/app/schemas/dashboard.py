"""Pydantic v2 schemas for Dashboard KPI stats."""

from pydantic import BaseModel


class DashboardStatsResponse(BaseModel):
    """Aggregated dashboard KPIs for a tenant."""

    active_conversations: int
    messages_today: int
    resolution_rate: float  # 0-100 percentage
    csat_score: float  # 0-5 scale
    total_contacts: int
    kb_documents_indexed: int
    unanswered_questions: int
    quota_usage: dict | None = None  # Reserved for future WhatsApp quota tracking
