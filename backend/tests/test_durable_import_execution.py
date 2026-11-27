"""Fail-safe outcomes for the staged PostgreSQL-driven import worker."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.dossier import import_execution as execution
from app.services.dossier.import_requests import ImportClaim, LostImportLeaseError


@pytest.fixture
def setup_execution(monkeypatch):
    @asynccontextmanager
    async def db_session():
        yield object()

    tenant = SimpleNamespace(id=uuid.uuid4(), slug="a", db_session=db_session)
    request_id = uuid.uuid4()
    claim = ImportClaim(
        request_id,
        tenant.id,
        uuid.uuid4(),
        f"imports/requests/{request_id.hex}/source.csv",
        "a" * 64,
        None,
        None,
    )
    claim_mock = AsyncMock(return_value=claim)
    finish_mock = AsyncMock()
    monkeypatch.setattr(execution, "claim_import", claim_mock)
    monkeypatch.setattr(execution, "finish_import", finish_mock)
    monkeypatch.setattr(execution, "quarantine_expired_imports", AsyncMock(return_value=0))
    return tenant, claim, claim_mock, finish_mock


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "status,expected", [("completed", "completed"), ("skipped", "completed"), ("failed", "failed")]
)
async def test_worker_passes_claim_and_does_not_finalize_twice(setup_execution, status, expected):
    tenant, claim, _, finish = setup_execution
    task = AsyncMock(return_value={"status": status})
    with patch("app.workers.import_dossier.task_import_dossier", task):
        assert await execution.process_one_durable_import(tenant) == expected
    task.assert_awaited_once()
    assert task.await_args.kwargs["durable_claim"] == claim
    finish.assert_not_awaited()


@pytest.mark.asyncio()
async def test_error_is_recorded_uncertain_without_retry(setup_execution):
    tenant, claim, _, finish = setup_execution
    task = AsyncMock(side_effect=RuntimeError("sensitive information"))
    with patch("app.workers.import_dossier.task_import_dossier", task):
        assert await execution.process_one_durable_import(tenant) == "uncertain"
    task.assert_awaited_once()
    assert finish.await_args.args[1] == claim
    assert finish.await_args.kwargs["outcome_code"] == "processing_error"


@pytest.mark.asyncio()
async def test_timeout_is_uncertain_and_lost_lease_is_not_retried(setup_execution):
    tenant, _, _, finish = setup_execution

    async def stall(*args, **kwargs):
        await asyncio.sleep(1)

    task = AsyncMock(side_effect=stall)
    with patch("app.workers.import_dossier.task_import_dossier", task):
        assert (
            await execution.process_one_durable_import(tenant, timeout_seconds=0.01) == "uncertain"
        )
    assert finish.await_args.kwargs["outcome_code"] == "processing_timeout"
    finish.side_effect = LostImportLeaseError("lost")
    with patch(
        "app.workers.import_dossier.task_import_dossier", new=AsyncMock(side_effect=RuntimeError())
    ):
        assert (
            await execution.process_one_durable_import(tenant) == "already_finalized_or_lease_lost"
        )


@pytest.mark.asyncio()
async def test_empty_registry_performs_no_send_or_import(setup_execution):
    tenant, _, claim_mock, finish = setup_execution
    claim_mock.return_value = None
    task = AsyncMock()
    with patch("app.workers.import_dossier.task_import_dossier", task):
        assert await execution.process_one_durable_import(tenant) == "empty"
    task.assert_not_awaited()
    finish.assert_not_awaited()
