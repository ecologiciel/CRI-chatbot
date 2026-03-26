"""Pydantic v2 schemas for incentive categories and items.

Used for CRUD operations on the incentive tree via back-office API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Category schemas ──


class IncentiveCategoryCreate(BaseModel):
    """Create a new incentive category."""

    parent_id: uuid.UUID | None = None
    name_fr: str = Field(..., min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    description_fr: str | None = None
    description_ar: str | None = None
    description_en: str | None = None
    order_index: int = Field(default=0, ge=0)
    is_leaf: bool = False
    icon: str | None = Field(default=None, max_length=50)


class IncentiveCategoryUpdate(BaseModel):
    """Update an existing incentive category. All fields optional."""

    name_fr: str | None = Field(default=None, min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    description_fr: str | None = None
    description_ar: str | None = None
    description_en: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_leaf: bool | None = None
    is_active: bool | None = None
    icon: str | None = Field(default=None, max_length=50)


class IncentiveCategoryResponse(BaseModel):
    """Category response with recursive children."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name_fr: str
    name_ar: str | None
    name_en: str | None
    description_fr: str | None
    description_ar: str | None
    description_en: str | None
    order_index: int
    is_leaf: bool
    is_active: bool
    icon: str | None
    children: list[IncentiveCategoryResponse] = []
    created_at: datetime
    updated_at: datetime


# Resolve forward reference for recursive model
IncentiveCategoryResponse.model_rebuild()


# ── Item schemas ──


class IncentiveItemCreate(BaseModel):
    """Create a new incentive item within a leaf category."""

    category_id: uuid.UUID
    title_fr: str = Field(..., min_length=2, max_length=500)
    title_ar: str | None = Field(default=None, max_length=500)
    title_en: str | None = Field(default=None, max_length=500)
    description_fr: str | None = None
    description_ar: str | None = None
    description_en: str | None = None
    conditions: str | None = None
    legal_reference: str | None = Field(default=None, max_length=500)
    eligibility_criteria: dict | None = None
    documents_required: list[str] = Field(default_factory=list)
    order_index: int = Field(default=0, ge=0)


class IncentiveItemUpdate(BaseModel):
    """Update an existing incentive item. All fields optional."""

    title_fr: str | None = Field(default=None, min_length=2, max_length=500)
    title_ar: str | None = Field(default=None, max_length=500)
    title_en: str | None = Field(default=None, max_length=500)
    description_fr: str | None = None
    description_ar: str | None = None
    description_en: str | None = None
    conditions: str | None = None
    legal_reference: str | None = Field(default=None, max_length=500)
    eligibility_criteria: dict | None = None
    documents_required: list[str] | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class IncentiveItemResponse(BaseModel):
    """Incentive item response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    title_fr: str
    title_ar: str | None
    title_en: str | None
    description_fr: str | None
    description_ar: str | None
    description_en: str | None
    conditions: str | None
    legal_reference: str | None
    eligibility_criteria: dict | None
    documents_required: list[str]
    order_index: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Tree response ──


class IncentiveTreeResponse(BaseModel):
    """Full incentive tree for a tenant. Root categories with nested children."""

    categories: list[IncentiveCategoryResponse]
