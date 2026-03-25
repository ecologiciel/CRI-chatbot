"""Pydantic v2 schemas for Admin CRUD.

IMPORTANT: AdminResponse NEVER exposes password_hash.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AdminRole


class AdminCreate(BaseModel):
    """Schema for creating a new admin."""

    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: AdminRole = AdminRole.viewer
    tenant_id: uuid.UUID | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Basic email validation."""
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            msg = "Invalid email format"
            raise ValueError(msg)
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce: 1 uppercase, 1 digit, 1 special character."""
        if not re.search(r"[A-Z]", v):
            msg = "Password must contain at least one uppercase letter"
            raise ValueError(msg)
        if not re.search(r"\d", v):
            msg = "Password must contain at least one digit"
            raise ValueError(msg)
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_=+\[\]\\;'/`~]", v):
            msg = "Password must contain at least one special character"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_role_tenant(self) -> AdminCreate:
        """super_admin must have no tenant; other roles require a tenant."""
        if self.role == AdminRole.super_admin and self.tenant_id is not None:
            msg = "super_admin must not be assigned to a specific tenant"
            raise ValueError(msg)
        if self.role != AdminRole.super_admin and self.tenant_id is None:
            msg = f"Role '{self.role.value}' requires a tenant_id"
            raise ValueError(msg)
        return self


class AdminUpdate(BaseModel):
    """Schema for updating an admin. All fields optional. No password field."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: AdminRole | None = None
    tenant_id: uuid.UUID | None = None
    is_active: bool | None = None


class AdminPasswordChange(BaseModel):
    """Schema for changing an admin's password."""

    current_password: str
    new_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            msg = "Password must contain at least one uppercase letter"
            raise ValueError(msg)
        if not re.search(r"\d", v):
            msg = "Password must contain at least one digit"
            raise ValueError(msg)
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_=+\[\]\\;'/`~]", v):
            msg = "Password must contain at least one special character"
            raise ValueError(msg)
        return v


class AdminResponse(BaseModel):
    """Admin response — NO password_hash exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: AdminRole
    tenant_id: uuid.UUID | None
    is_active: bool
    last_login: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminList(BaseModel):
    """Paginated list of admins."""

    items: list[AdminResponse]
    total: int
    page: int
    page_size: int
