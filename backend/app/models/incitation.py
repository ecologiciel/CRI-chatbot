"""Incentive models — stored in the TENANT schema.

Tree structure for investment incentives navigation:
- IncentiveCategory: hierarchical categories (self-referencing parent_id)
- IncentiveItem: individual incentive entries within leaf categories
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    pass


class IncentiveCategory(UUIDMixin, TimestampMixin, Base):
    """Hierarchical category for incentive navigation.

    Forms a tree via parent_id (null = root category).
    Leaf categories (is_leaf=True) contain IncentiveItems.
    """

    __tablename__ = "incentive_categories"
    __table_args__ = (
        Index("ix_incentive_categories_parent_id", "parent_id"),
        Index("ix_incentive_categories_order_index", "order_index"),
        Index("ix_incentive_categories_is_active", "is_active"),
    )

    # Tree structure
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incentive_categories.id", ondelete="CASCADE"),
        nullable=True,
        comment="Null = root category",
    )

    # Multilingual names
    name_fr: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="French name"
    )
    name_ar: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Arabic name"
    )
    name_en: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="English name"
    )

    # Multilingual descriptions
    description_fr: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    description_ar: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    description_en: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # Display
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Sort order within sibling categories",
    )
    is_leaf: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="True = contains items, no sub-categories",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    icon: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Lucide icon name for back-office",
    )

    # Relationships
    children: Mapped[list[IncentiveCategory]] = relationship(
        "IncentiveCategory",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="IncentiveCategory.order_index",
    )
    parent: Mapped[IncentiveCategory | None] = relationship(
        "IncentiveCategory",
        back_populates="children",
        remote_side="IncentiveCategory.id",
    )
    items: Mapped[list[IncentiveItem]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="IncentiveItem.order_index",
    )

    def __repr__(self) -> str:
        return f"<IncentiveCategory name_fr={self.name_fr!r} is_leaf={self.is_leaf}>"


class IncentiveItem(UUIDMixin, TimestampMixin, Base):
    """Individual incentive entry within a leaf category.

    Contains multilingual content, eligibility criteria,
    and required documents for a specific incentive.
    """

    __tablename__ = "incentive_items"
    __table_args__ = (
        Index("ix_incentive_items_category_id", "category_id"),
        Index("ix_incentive_items_order_index", "order_index"),
        Index("ix_incentive_items_is_active", "is_active"),
    )

    # Parent category
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incentive_categories.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Multilingual titles
    title_fr: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="French title"
    )
    title_ar: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Arabic title"
    )
    title_en: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="English title"
    )

    # Multilingual descriptions
    description_fr: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    description_ar: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    description_en: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # Content
    conditions: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Eligibility conditions (free text)",
    )
    legal_reference: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Law/decree reference",
    )
    eligibility_criteria: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None,
        comment="Structured eligibility criteria",
    )
    documents_required: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
        comment="List of required documents",
    )

    # Display
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )

    # Relationships
    category: Mapped[IncentiveCategory] = relationship(
        back_populates="items",
    )

    def __repr__(self) -> str:
        return f"<IncentiveItem title_fr={self.title_fr!r} category_id={self.category_id}>"
