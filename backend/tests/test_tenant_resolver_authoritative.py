"""New requests must not reuse stale tenant identity or authorization state."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import TenantInactiveError, TenantNotFoundError
from app.core.tenant import TenantResolver
from app.models.enums import TenantStatus


def tenant(status=TenantStatus.active):
    return SimpleNamespace(
        id=uuid.uuid4(), slug="onssa", name="ONSSA", status=status, whatsapp_config=None
    )


def session_for(value):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = MagicMock(scalar_one_or_none=lambda: value)
    return session


@pytest.mark.asyncio
async def test_slug_rechecks_inactive_status_in_database():
    item = tenant()
    session = session_for(item)
    with patch("app.core.tenant.get_session_factory", return_value=lambda: session):
        assert (await TenantResolver.from_slug("onssa")).id == item.id
        item.status = TenantStatus.inactive
        with pytest.raises(TenantInactiveError):
            await TenantResolver.from_slug("onssa")
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_id_lookup_does_not_resurrect_deleted_tenant():
    item = tenant()
    session = session_for(item)
    with patch("app.core.tenant.get_session_factory", return_value=lambda: session):
        assert (await TenantResolver.from_tenant_id_header(str(item.id))).id == item.id
        session.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
        with pytest.raises(TenantNotFoundError):
            await TenantResolver.from_tenant_id_header(str(item.id))


@pytest.mark.asyncio
async def test_phone_lookup_rechecks_database_and_current_mapping():
    first = tenant()
    second = tenant()
    session = session_for(first)
    with patch("app.core.tenant.get_session_factory", return_value=lambda: session):
        assert (await TenantResolver.from_phone_number_id("123")).id == first.id
        session.execute.return_value = MagicMock(scalar_one_or_none=lambda: second)
        assert (await TenantResolver.from_phone_number_id("123")).id == second.id
        session.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
        with pytest.raises(TenantNotFoundError):
            await TenantResolver.from_phone_number_id("123")


@pytest.mark.asyncio
async def test_database_failure_does_not_use_cached_active_tenant():
    session = session_for(None)
    session.execute.side_effect = RuntimeError("database unavailable")
    with patch("app.core.tenant.get_session_factory", return_value=lambda: session):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await TenantResolver.from_slug("onssa")
