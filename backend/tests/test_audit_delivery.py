"""Audit completion and failure must be visible without changing committed responses."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.audit_middleware import AuditMiddleware
from app.schemas.audit import AuditLogCreate
from app.services.audit.service import AuditService


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_mutation_waits_for_audit_and_reports_outcome(outcome):
    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.post("/api/v1/example")
    async def mutate():
        return {"committed": True}

    async def write(_data):
        if outcome == "timeout":
            await asyncio.sleep(1)
        return outcome == "success"

    metric = MagicMock()
    write_mock = AsyncMock(side_effect=write)
    with (
        patch("app.core.audit_middleware._fire_audit", write_mock),
        patch("app.core.audit_middleware.AUDIT_WRITE_TOTAL", metric),
        patch("app.core.audit_middleware.AUDIT_TIMEOUT_SECONDS", 0.02),
        TestClient(app) as client,
    ):
        response = client.post("/api/v1/example")
    assert response.status_code == 200
    assert response.json() == {"committed": True}
    write_mock.assert_awaited_once()
    if outcome == "timeout":
        metric.labels.assert_called_once_with(outcome="timeout")
        metric.labels.return_value.inc.assert_called_once()
    else:
        metric.labels.assert_not_called()


@pytest.mark.asyncio
async def test_audit_error_does_not_log_exception_contents():
    service = AuditService()
    service._logger = MagicMock()
    data = AuditLogCreate(tenant_slug="fixture", user_type="system", action="create", resource_type="test")
    metric = MagicMock()
    with (
        patch("app.services.audit.service.get_session_factory", side_effect=RuntimeError("private-value")),
        patch("app.services.audit.service.AUDIT_WRITE_TOTAL", metric),
    ):
        assert await service.log_action(data) is False
    assert "private-value" not in str(service._logger.error.call_args)
    metric.labels.assert_called_once_with(outcome="failure")
