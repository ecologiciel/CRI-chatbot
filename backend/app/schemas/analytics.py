"""Pydantic v2 schemas for analytics endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class AnalyticsOverviewResponse(BaseModel):
    """Aggregated KPIs with trend vs previous period."""

    conversations_total: int
    conversations_trend: float
    messages_total: int
    messages_trend: float
    resolution_rate: float
    resolution_trend: float
    csat_average: float
    csat_trend: float


class TimeSeriesPoint(BaseModel):
    """Single data point in a daily time series."""

    date: str
    conversations: int
    messages: int
    escalations: int


class LanguageDistribution(BaseModel):
    """Conversation count per language."""

    language: str
    label: str
    count: int
    percentage: float


class QuestionTypeDistribution(BaseModel):
    """Conversation breakdown by question type."""

    type: str
    label: str
    count: int
    percentage: float


class TopQuestion(BaseModel):
    """Frequently asked unanswered question."""

    question: str
    count: int
    avg_confidence: float
    status: str
