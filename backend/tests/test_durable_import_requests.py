import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.dossier.import_requests import (
    ImportClaim,
    ImportConfigurationChangedError,
    finish_import,
    mapping_digest,
    register_import,
    verified_claim_mapping,
)


def test_mapping_digest_is_canonical_and_rejects_invalid_values():
    assert mapping_digest({"b": "statut", "a": "numero"}) == mapping_digest(
        {"a": "numero", "b": "statut"}
    )
    assert mapping_digest({}) == mapping_digest(None)
    assert mapping_digest({"a": "statut"}) != mapping_digest({"a": "numero"})
    with pytest.raises(ValueError):
        mapping_digest({"a": ["numero"]})
    with pytest.raises(ValueError):
        mapping_digest([])


@pytest.mark.asyncio()
async def test_automatic_mapping_is_bound_to_no_config():
    session = AsyncMock()
    claim = ImportClaim(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "key", "a" * 64, None, None)
    assert await verified_claim_mapping(session, claim) is None
    session.execute.assert_not_awaited()
    altered = ImportClaim(
        claim.request_id,
        claim.tenant_id,
        claim.token,
        claim.object_key,
        claim.content_sha256,
        None,
        None,
        "a" * 64,
    )
    with pytest.raises(ImportConfigurationChangedError):
        await verified_claim_mapping(session, altered)


@pytest.mark.asyncio()
async def test_rejects_untrusted_source_key_and_hash_before_writing():
    session = AsyncMock()
    request_id = uuid.uuid4()
    with pytest.raises(ValueError):
        await register_import(
            session,
            request_id=request_id,
            tenant_id=uuid.uuid4(),
            object_key="imports/requests/other/source.csv",
            content_sha256="a" * 64,
            sync_config_id=None,
            requested_by=None,
        )
    with pytest.raises(ValueError):
        await register_import(
            session,
            request_id=request_id,
            tenant_id=uuid.uuid4(),
            object_key=f"imports/requests/{request_id.hex}/source.csv",
            content_sha256="bad",
            sync_config_id=None,
            requested_by=None,
        )
    session.flush.assert_not_awaited()


@pytest.mark.asyncio()
async def test_completed_import_requires_traceable_sync_log():
    session = AsyncMock()
    claim = ImportClaim(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "unused", "a" * 64, None, None)
    with pytest.raises(ValueError):
        await finish_import(
            session, claim, state="completed", outcome_code="imported", sync_log_id=None
        )
    session.execute.assert_not_awaited()
