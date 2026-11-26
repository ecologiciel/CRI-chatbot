"""Created admin addresses must also be accepted by login."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.admin import AdminCreate
from app.schemas.auth import LoginRequest


def admin(email: str) -> AdminCreate:
    return AdminCreate(
        email=email,
        password="Example!123456",
        full_name="Test",
        role="admin_tenant",
        tenant_id=uuid.uuid4(),
    )


def test_address_is_normalized_and_accepted_by_login():
    created = admin("Test.User@Example.COM")
    assert created.email == "test.user@example.com"
    assert LoginRequest(email=created.email, password="anything").email == created.email


def test_unusable_special_use_email_is_rejected_at_creation():
    with pytest.raises(ValidationError):
        admin("test@example.invalid")
