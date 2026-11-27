from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.import_dossier import poll_durable_imports


@pytest.mark.asyncio()
async def test_disabled_poll_does_not_query_database():
    with (
        patch("app.workers.import_dossier.get_settings") as settings,
        patch("app.core.database.get_session_factory") as factory,
    ):
        settings.return_value.dossier_durable_imports_enabled = False
        assert await poll_durable_imports({}) == "disabled"
        factory.assert_not_called()


@pytest.mark.asyncio()
async def test_poll_uses_postgres_and_processes_at_most_one_institution():
    result = MagicMock()
    result.scalar_one_or_none.return_value = "institution"
    session = AsyncMock()
    session.execute.return_value = result
    session.__aenter__.return_value = session
    tenant = SimpleNamespace(slug="institution")
    with (
        patch("app.workers.import_dossier.get_settings") as settings,
        patch("app.core.database.get_session_factory", return_value=lambda: session),
        patch("app.core.tenant.TenantResolver.from_slug", new=AsyncMock(return_value=tenant)),
        patch(
            "app.services.dossier.import_execution.process_one_durable_import",
            new=AsyncMock(return_value="completed"),
        ) as process,
    ):
        settings.return_value.dossier_durable_imports_enabled = True
        assert await poll_durable_imports({}) == "completed"
    process.assert_awaited_once_with(tenant)
