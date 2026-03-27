"""Tests for InternalWhitelist model and Pydantic schemas.

Validates:
- SQLAlchemy model structure (columns, table args)
- Pydantic schema validation (phone E.164, required fields, optional fields)
- Edge cases for phone format validation
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.whitelist import InternalWhitelist
from app.schemas.whitelist import (
    InternalWhitelistCreate,
    InternalWhitelistList,
    InternalWhitelistResponse,
    InternalWhitelistUpdate,
    WhitelistCheckResponse,
)


# ── Constants ──

TEST_PHONE = "+212600000001"
TEST_PHONE_INTL = "+14155552671"


# ---------------------------------------------------------------------------
# Model structure tests
# ---------------------------------------------------------------------------


class TestInternalWhitelistModel:
    """Verify SQLAlchemy model metadata."""

    def test_tablename(self):
        """Table name is internal_whitelist."""
        assert InternalWhitelist.__tablename__ == "internal_whitelist"

    def test_no_explicit_schema(self):
        """Tenant schema tables must NOT set an explicit schema in __table_args__."""
        args = InternalWhitelist.__table_args__
        if isinstance(args[-1], dict):
            assert "schema" not in args[-1]

    def test_has_required_columns(self):
        """Model defines all expected columns."""
        column_names = {c.name for c in InternalWhitelist.__table__.columns}
        expected = {
            "id", "phone", "label", "note", "is_active",
            "added_by", "created_at", "updated_at",
        }
        assert expected == column_names

    def test_phone_column_not_nullable(self):
        """Phone column must be NOT NULL."""
        col = InternalWhitelist.__table__.c.phone
        assert col.nullable is False

    def test_added_by_nullable(self):
        """added_by is nullable (admin may be deleted)."""
        col = InternalWhitelist.__table__.c.added_by
        assert col.nullable is True

    def test_is_active_not_nullable(self):
        """is_active must be NOT NULL."""
        col = InternalWhitelist.__table__.c.is_active
        assert col.nullable is False

    def test_repr(self):
        """__repr__ includes phone and is_active."""
        wl = InternalWhitelist()
        wl.phone = "+212612345678"
        wl.is_active = True
        r = repr(wl)
        assert "+212612345678" in r
        assert "is_active=True" in r


# ---------------------------------------------------------------------------
# Create schema tests
# ---------------------------------------------------------------------------


class TestInternalWhitelistCreate:
    """Validation for InternalWhitelistCreate schema."""

    def test_valid_moroccan_phone(self):
        """Moroccan phone in E.164 accepted."""
        obj = InternalWhitelistCreate(phone=TEST_PHONE)
        assert obj.phone == TEST_PHONE

    def test_valid_international_phone(self):
        """International phone in E.164 accepted."""
        obj = InternalWhitelistCreate(phone=TEST_PHONE_INTL)
        assert obj.phone == TEST_PHONE_INTL

    def test_valid_with_label_and_note(self):
        """All optional fields accepted."""
        obj = InternalWhitelistCreate(
            phone=TEST_PHONE,
            label="Mohammed Alami",
            note="CRI employee, department investments",
        )
        assert obj.label == "Mohammed Alami"
        assert obj.note is not None

    def test_phone_missing_plus(self):
        """Phone without leading + is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="212600000001")

    def test_phone_leading_zero(self):
        """Phone starting with +0 is rejected (E.164 requires non-zero)."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="+0212600000001")

    def test_phone_too_short(self):
        """Phone with fewer than 7 digits after + is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="+12345")

    def test_phone_too_long(self):
        """Phone with more than 15 digits total is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="+1234567890123456")

    def test_phone_with_spaces(self):
        """Phone with spaces is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="+212 600 000 001")

    def test_phone_with_dashes(self):
        """Phone with dashes is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone="+212-600-000-001")

    def test_phone_required(self):
        """Phone is required (no default)."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate()

    def test_label_max_length(self):
        """Label exceeding 255 chars is rejected."""
        with pytest.raises(ValidationError):
            InternalWhitelistCreate(phone=TEST_PHONE, label="x" * 256)

    def test_defaults(self):
        """label and note default to None."""
        obj = InternalWhitelistCreate(phone=TEST_PHONE)
        assert obj.label is None
        assert obj.note is None


# ---------------------------------------------------------------------------
# Update schema tests
# ---------------------------------------------------------------------------


class TestInternalWhitelistUpdate:
    """Validation for InternalWhitelistUpdate schema."""

    def test_all_fields_optional(self):
        """Empty update is valid (no required fields)."""
        obj = InternalWhitelistUpdate()
        assert obj.label is None
        assert obj.note is None
        assert obj.is_active is None

    def test_deactivate(self):
        """Setting is_active=False is valid."""
        obj = InternalWhitelistUpdate(is_active=False)
        assert obj.is_active is False

    def test_update_label(self):
        """Updating label is valid."""
        obj = InternalWhitelistUpdate(label="New label")
        assert obj.label == "New label"

    def test_no_phone_field(self):
        """Phone cannot be updated (field does not exist on Update schema)."""
        assert "phone" not in InternalWhitelistUpdate.model_fields


# ---------------------------------------------------------------------------
# Response schema tests
# ---------------------------------------------------------------------------


class TestInternalWhitelistResponse:
    """Validation for InternalWhitelistResponse schema."""

    def test_from_attributes_enabled(self):
        """Response schema has from_attributes=True for ORM compatibility."""
        assert InternalWhitelistResponse.model_config.get("from_attributes") is True

    def test_all_fields_present(self):
        """Response schema contains all expected fields."""
        fields = set(InternalWhitelistResponse.model_fields.keys())
        expected = {
            "id", "phone", "label", "note", "is_active",
            "added_by", "created_at", "updated_at",
        }
        assert expected == fields


# ---------------------------------------------------------------------------
# List schema tests
# ---------------------------------------------------------------------------


class TestInternalWhitelistList:
    """Validation for InternalWhitelistList schema."""

    def test_pagination_fields(self):
        """List schema has standard pagination fields."""
        fields = set(InternalWhitelistList.model_fields.keys())
        assert {"items", "total", "page", "page_size"} == fields


# ---------------------------------------------------------------------------
# Check response tests
# ---------------------------------------------------------------------------


class TestWhitelistCheckResponse:
    """Validation for WhitelistCheckResponse schema."""

    def test_whitelisted(self):
        """Whitelisted phone returns is_whitelisted=True."""
        obj = WhitelistCheckResponse(phone=TEST_PHONE, is_whitelisted=True)
        assert obj.is_whitelisted is True

    def test_not_whitelisted(self):
        """Non-whitelisted phone returns is_whitelisted=False."""
        obj = WhitelistCheckResponse(phone=TEST_PHONE, is_whitelisted=False)
        assert obj.is_whitelisted is False
