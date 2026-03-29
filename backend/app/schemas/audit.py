"""Pydantic v2 schemas for the audit trail system.

AuditLogCreate: internal use by AuditService (not exposed via API).
AuditLogRead: response model for audit log entries.
AuditLogFilter: query parameters for filtering in super-admin UI.
AuditLogList: paginated response wrapper.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AuditLogCreate(BaseModel):
    """Schema for creating an audit log entry (internal use).

    Used by AuditService.log_action() and AuditMiddleware.
    The details field must NEVER contain PII (passwords, tokens, CIN, etc.).
    """

    tenant_slug: str = Field(..., max_length=50)
    user_id: uuid.UUID | None = None
    user_type: str = Field(..., max_length=20)
    action: str = Field(..., max_length=20)
    resource_type: str = Field(..., max_length=100)
    resource_id: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=45)
    user_agent: str | None = None
    details: dict | None = None


class AuditLogRead(BaseModel):
    """Schema for reading an audit log entry (API response)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_slug: str
    user_id: uuid.UUID | None
    user_type: str
    action: str
    resource_type: str
    resource_id: str | None
    ip_address: str | None
    user_agent: str | None
    details: dict | None
    created_at: datetime


class AuditLogFilter(BaseModel):
    """Query parameters for filtering audit logs in the super-admin UI."""

    tenant_slug: str | None = None
    user_id: uuid.UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class AuditLogList(BaseModel):
    """Paginated list of audit log entries."""

    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
