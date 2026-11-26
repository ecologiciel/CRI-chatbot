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


@pytest.mark.asyncio
async def test_admin_creation_refuses_inactive_tenant():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.api.v1.admins import create_admin
    from app.core.exceptions import ValidationError as AppValidationError
    from app.models.enums import TenantStatus
    from app.schemas.auth import AdminTokenPayload

    data = admin("test@example.com")
    caller = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role="super_admin",
        tenant_id=None,
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = MagicMock(scalar_one_or_none=lambda: TenantStatus.inactive)
    with patch("app.api.v1.admins.get_session_factory", return_value=lambda: session):
        with pytest.raises(AppValidationError, match="institution inactive"):
            await create_admin(data, caller)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
