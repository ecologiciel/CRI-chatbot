"""Pydantic v2 schemas for the notification API (Wave 25B).

NotificationHistoryItem: reshaped audit_log entry for notification history.
NotificationHistoryList: paginated response wrapper.
NotificationStats: aggregated statistics over a period.
ManualNotificationRequest / Response: manual send endpoint.
NotificationTemplateRead / Update: template management.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.services.notification.service import NotificationEventType

# ── Helpers ─────────────────────────────────────────────────────────

_ACTION_TO_STATUS: dict[str, str] = {
    "notification_sent": "sent",
    "notification_skipped": "skipped",
    "notification_failed": "failed",
    "notif_manual_sent": "sent",
}

_VALID_EVENT_TYPES = {e.value for e in NotificationEventType}


def audit_action_to_status(action: str) -> str:
    """Map an audit_log action to a user-facing notification status."""
    return _ACTION_TO_STATUS.get(action, action)


# ── History ─────────────────────────────────────────────────────────


class NotificationHistoryItem(BaseModel):
    """Single notification history entry (derived from audit_logs)."""

    id: uuid.UUID
    event_type: str | None = None
    status: str
    contact_id: str | None = None
    dossier_id: str | None = None
    dossier_numero: str | None = None
    template_name: str | None = None
    wamid: str | None = None
    reason: str | None = None
    created_at: datetime


class NotificationHistoryList(BaseModel):
    """Paginated list of notification history entries."""

    items: list[NotificationHistoryItem]
    total: int
    page: int
    page_size: int


# ── Stats ───────────────────────────────────────────────────────────


class NotificationStats(BaseModel):
    """Aggregated notification statistics over a period."""

    total_sent: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    by_event_type: dict[str, int] = Field(default_factory=dict)
    period_days: int = 30


# ── Manual send ─────────────────────────────────────────────────────


class ManualNotificationRequest(BaseModel):
    """Request body for manual notification send."""

    contact_id: uuid.UUID
    dossier_id: uuid.UUID
    event_type: str = Field(
        ...,
        description="One of: decision_finale, complement_request, status_update, dossier_incomplet",
    )

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in _VALID_EVENT_TYPES:
            msg = f"Invalid event_type '{v}'. Must be one of: {sorted(_VALID_EVENT_TYPES)}"
            raise ValueError(msg)
        return v


class ManualNotificationResponse(BaseModel):
    """Response for manual notification send."""

    status: str
    wamid: str | None = None
    reason: str | None = None


# ── Templates ───────────────────────────────────────────────────────


class NotificationTemplateRead(BaseModel):
    """Read model for a notification template mapping."""

    event_type: str
    template_name: str
    description: str
    priority: str


class NotificationTemplateUpdate(BaseModel):
    """Request body for updating a template mapping."""

    template_name: str = Field(..., min_length=1, max_length=200)
