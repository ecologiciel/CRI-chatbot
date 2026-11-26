"""Lifecycle locks guard ingestion against concurrent tenant removal."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import TenantInactiveError, TenantLifecycleBusyError
from app.core.tenant import TenantContext
from app.core.tenant_lifecycle import protect_ingestion, protect_removal
from app.main import _get_status_code
from app.models.enums import TenantStatus


def make_session(results):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.side_effect = results
    return session


def active_tenant():
    return TenantContext(uuid.uuid4(), "onssa", "ONSSA", "active", None)


@pytest.mark.asyncio
async def test_shared_lock_rechecks_current_identity_and_status():
    tenant = active_tenant()
    session = make_session(
        [
            MagicMock(),
            MagicMock(
                one_or_none=lambda: SimpleNamespace(id=tenant.id, status=TenantStatus.active)
            ),
        ]
    )
    with patch("app.core.tenant_lifecycle.get_session_factory", return_value=lambda: session):
        async with protect_ingestion(tenant):
            assert session.execute.await_count == 2
    lock_call = session.execute.await_args_list[0]
    assert "pg_advisory_xact_lock_shared" in str(lock_call.args[0])
    assert lock_call.args[1]["key"] == "tenant-lifecycle:onssa"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["deleted", "inactive", "recreated"])
async def test_ingestion_fails_closed_when_tenant_changes(mode):
    tenant = active_tenant()
    row = {
        "deleted": None,
        "inactive": SimpleNamespace(id=tenant.id, status=TenantStatus.inactive),
        "recreated": SimpleNamespace(id=uuid.uuid4(), status=TenantStatus.active),
    }[mode]
    session = make_session([MagicMock(), MagicMock(one_or_none=lambda: row)])
    with patch("app.core.tenant_lifecycle.get_session_factory", return_value=lambda: session):
        with pytest.raises(TenantInactiveError):
            async with protect_ingestion(tenant):
                pytest.fail("inactive tenant was accepted")


@pytest.mark.asyncio
async def test_removal_refuses_busy_tenant_with_conflict():
    session = make_session([MagicMock(scalar_one=lambda: False)])
    with patch("app.core.tenant_lifecycle.get_session_factory", return_value=lambda: session):
        with pytest.raises(TenantLifecycleBusyError) as exc:
            async with protect_removal("onssa"):
                pytest.fail("busy tenant was removed")
    assert _get_status_code(exc.value) == 409
    assert "pg_try_advisory_xact_lock" in str(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_removal_accepts_available_lock_and_rejects_unsafe_slug():
    session = make_session([MagicMock(scalar_one=lambda: True)])
    with patch("app.core.tenant_lifecycle.get_session_factory", return_value=lambda: session):
        async with protect_removal("onssa"):
            pass
        with pytest.raises(ValueError):
            async with protect_removal("onssa*"):
                pass
