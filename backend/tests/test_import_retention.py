from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.dossier.import_retention import purge_import_sources, purge_one_import_source


@pytest.mark.asyncio
async def test_retention_disabled_never_touches_database_or_storage():
    settings = SimpleNamespace(
        dossier_durable_imports_enabled=True, dossier_import_retention_days=0
    )
    with (
        patch("app.services.dossier.import_retention.get_settings", return_value=settings),
        patch("app.services.dossier.import_retention.get_session_factory") as factory,
        patch("app.services.dossier.import_retention.get_minio") as storage,
    ):
        assert await purge_import_sources({}) == {"deleted": 0, "tenants_failed": 0}
    factory.assert_not_called()
    storage.assert_not_called()


@pytest.mark.asyncio
async def test_retention_rejects_invalid_duration():
    with pytest.raises(ValueError):
        await purge_one_import_source(None, "tenant", 0, None)
