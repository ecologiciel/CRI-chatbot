"""Pydantic v2 schemas for Escalation management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EscalationPriority, EscalationStatus, EscalationTrigger


class EscalationCreate(BaseModel):
    """Schema for creating an escalation — used internally by the service layer."""

    conversation_id: uuid.UUID
    trigger_type: EscalationTrigger
    priority: EscalationPriority
    context_summary: str | None = None
    user_message: str | None = None


class EscalationRead(BaseModel):
    """Escalation response — returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    trigger_type: EscalationTrigger
    priority: EscalationPriority
    assigned_to: uuid.UUID | None
    context_summary: str | None
    user_message: str | None
    status: EscalationStatus
    resolution_notes: str | None
    created_at: datetime
    assigned_at: datetime | None
    resolved_at: datetime | None

    # Computed: seconds waiting since creation (only for pending/assigned)
    wait_time_seconds: int | None = None

    @model_validator(mode="after")
    def compute_wait_time(self) -> EscalationRead:
        """Compute wait time for escalations not yet resolved."""
        if self.status in {EscalationStatus.pending, EscalationStatus.assigned}:
            now = datetime.now(UTC)
            created = self.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            self.wait_time_seconds = int((now - created).total_seconds())
        return self


class EscalationList(BaseModel):
    """Paginated list of escalations."""

    items: list[EscalationRead]
    total: int
    page: int
    page_size: int


class EscalationAssign(BaseModel):
    """Payload to assign an escalation to a human agent."""

    admin_id: uuid.UUID


class EscalationResolve(BaseModel):
    """Payload to resolve/close an escalation."""

    resolution_notes: str = Field(..., min_length=1)


class EscalationRespond(BaseModel):
    """Payload for the human agent to send a WhatsApp message."""

    message: str = Field(..., min_length=1)


class EscalationStats(BaseModel):
    """Dashboard statistics for the escalation queue."""

    total_pending: int
    total_in_progress: int
    avg_wait_seconds: float | None = None
    avg_resolution_seconds: float | None = None
    by_trigger: dict[str, int]
    by_priority: dict[str, int]
