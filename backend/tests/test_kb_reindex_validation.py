"""Reindex must preserve the knowledge-base approval boundary."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.kb import _enqueue_ingestion, _ensure_reindexable
from app.core.exceptions import ValidationError
from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus


def document(**overrides):
    values = {
        "validated_at": datetime.now(UTC), "validated_by": uuid.uuid4(),
        "status": KBDocumentStatus.indexed, "source_authority": "ONSSA",
        "source_reference": "Guide", "source_version": "v1", "published_at": date.today(),
        "expires_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_approved_document_can_be_reindexed():
    _ensure_reindexable(document())


@pytest.mark.parametrize("override", [
    {"validated_at": None},
    {"validated_by": None},
    {"status": KBDocumentStatus.pending_validation},
    {"status": KBDocumentStatus.rejected},
    {"expires_at": date.today() - timedelta(days=1)},
    {"source_authority": None},
])
def test_unapproved_or_expired_document_cannot_be_reindexed(override):
    with pytest.raises(ValidationError):
        _ensure_reindexable(document(**override))


@pytest.mark.asyncio
async def test_enqueue_failure_marks_only_pending_document_without_leaking_error():
    tenant = TenantContext(uuid.uuid4(), "onssa", "ONSSA", "active", None)
    session = AsyncMock()

    @asynccontextmanager
    async def db_session(_self):
        yield session

    queue = SimpleNamespace(enqueue_job=AsyncMock(side_effect=RuntimeError("provider secret")))
    with patch("app.api.v1.kb.get_arq_pool", return_value=queue), patch.object(TenantContext, "db_session", db_session):
        with pytest.raises(HTTPException) as exc:
            await _enqueue_ingestion(tenant, uuid.uuid4(), "ingest_document_task")
    assert exc.value.status_code == 503
    assert "secret" not in exc.value.detail
    statement = str(session.execute.await_args.args[0])
    assert "kb_documents.status" in statement
