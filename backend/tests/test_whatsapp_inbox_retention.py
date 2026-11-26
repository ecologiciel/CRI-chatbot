from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.whatsapp.inbox_retention import _redact_tenant
from app.workers.purge import WorkerSettings


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, -1, 3651])
async def test_invalid_retention_is_rejected_before_database_access(days):
    with pytest.raises(ValueError):
        await _redact_tenant(uuid4(), "tenant_a", days, datetime.now(UTC))


def test_retention_runs_on_the_isolated_purge_queue():
    assert WorkerSettings.queue_name == "arq:queue:purge"
    assert any(job.name.endswith("redact_expired_inbox") for job in WorkerSettings.cron_jobs)
