from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tenant.provisioning import TenantProvisioningService


@pytest.mark.asyncio
async def test_restricted_schema_drop_binds_slug_and_commits():
    session = AsyncMock()
    session.__aenter__.return_value = session
    factory = MagicMock(return_value=session)
    with (
        patch("app.services.tenant.provisioning.get_session_factory", return_value=factory),
        patch("app.services.tenant.provisioning.get_settings") as settings,
    ):
        settings.return_value.restricted_tenant_schema_drop_enabled = True
        await TenantProvisioningService()._drop_schema("institution_a")
    statement, params = session.execute.await_args.args
    assert str(statement) == "SELECT public.rehearsal_drop_tenant_schema(:slug)"
    assert params == {"slug": "institution_a"}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["template", "../invalid", "x;DROP SCHEMA public", ""])
async def test_schema_drop_rejects_invalid_slug_before_database_access(slug):
    with patch("app.services.tenant.provisioning.get_session_factory") as factory:
        with pytest.raises(ValueError):
            await TenantProvisioningService()._drop_schema(slug)
    factory.assert_not_called()
