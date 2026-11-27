"""Transactional primitives for staged durable dossier imports.

The guarded durable mode uses this registry. A successful import calls
``finish_import`` in the *same transaction* as the dossier and history changes.
Expired leases become uncertain and are never auto-replayed.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dossier_import_request import DossierImportRequest
from app.models.sync import SyncConfig


def mapping_digest(mapping: dict | None) -> str:
    """Bind interpretation without storing column names in the shared registry."""
    normalized = None if mapping is None or mapping == {} else mapping
    if normalized is not None and (
        not isinstance(normalized, dict)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in normalized.items())
    ):
        raise ValueError("invalid import column mapping")
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


EMPTY_MAPPING_DIGEST = mapping_digest(None)


class LostImportLeaseError(RuntimeError):
    """The enclosing transaction must roll back; the claim is no longer current."""


class ImportConfigurationConflictError(ValueError):
    """The same file already exists with different import configuration."""


class ImportConfigurationChangedError(ValueError):
    """An accepted import configuration changed or became unavailable."""


@dataclass(frozen=True, slots=True)
class ImportClaim:
    request_id: uuid.UUID
    tenant_id: uuid.UUID
    token: uuid.UUID
    object_key: str
    content_sha256: str
    sync_config_id: uuid.UUID | None
    requested_by: uuid.UUID | None
    mapping_sha256: str = EMPTY_MAPPING_DIGEST


async def verified_claim_mapping(session: AsyncSession, claim: ImportClaim) -> dict | None:
    """Read and lock the tenant mapping for the surrounding transaction."""
    if claim.sync_config_id is None:
        if claim.mapping_sha256 != EMPTY_MAPPING_DIGEST:
            raise ImportConfigurationChangedError("import mapping no longer matches")
        return None
    config = (
        await session.execute(
            select(SyncConfig)
            .where(SyncConfig.id == claim.sync_config_id)
            .with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if config is None or not config.is_active:
        raise ImportConfigurationChangedError("import configuration unavailable")
    try:
        matches = mapping_digest(config.column_mapping) == claim.mapping_sha256
    except ValueError as exc:
        raise ImportConfigurationChangedError("import mapping invalid") from exc
    if not matches:
        raise ImportConfigurationChangedError("import mapping changed")
    return dict(config.column_mapping) if config.column_mapping else None


async def find_existing_import(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    content_sha256: str,
    sync_config_id: uuid.UUID | None,
    mapping_sha256: str = EMPTY_MAPPING_DIGEST,
) -> uuid.UUID | None:
    existing = (
        await session.execute(
            select(
                DossierImportRequest.id,
                DossierImportRequest.sync_config_id,
                DossierImportRequest.mapping_sha256,
            ).where(
                DossierImportRequest.tenant_id == tenant_id,
                DossierImportRequest.content_sha256 == content_sha256,
                DossierImportRequest.state != "failed",
            )
        )
    ).one_or_none()
    if existing is None:
        return None
    if existing.sync_config_id != sync_config_id or existing.mapping_sha256 != mapping_sha256:
        raise ImportConfigurationConflictError(
            "file already registered with different configuration"
        )
    return existing.id


async def register_import(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    tenant_id: uuid.UUID,
    object_key: str,
    content_sha256: str,
    sync_config_id: uuid.UUID | None,
    requested_by: uuid.UUID | None,
    mapping_sha256: str = EMPTY_MAPPING_DIGEST,
) -> tuple[uuid.UUID, bool]:
    """Record only generated object keys, after successful object storage."""
    prefix = f"imports/requests/{request_id.hex}/source."
    if object_key not in {prefix + ext for ext in ("csv", "xls", "xlsx")}:
        raise ValueError("invalid import object key")
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError("invalid import content hash")
    if not re.fullmatch(r"[0-9a-f]{64}", mapping_sha256):
        raise ValueError("invalid import mapping hash")
    result = await session.execute(
        insert(DossierImportRequest)
        .values(
            id=request_id,
            tenant_id=tenant_id,
            object_key=object_key,
            content_sha256=content_sha256,
            mapping_sha256=mapping_sha256,
            sync_config_id=sync_config_id,
            requested_by=requested_by,
        )
        .on_conflict_do_nothing()
        .returning(DossierImportRequest.id)
    )
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        return inserted_id, True
    existing = await find_existing_import(
        session, tenant_id, content_sha256, sync_config_id, mapping_sha256
    )
    if existing is None:
        raise RuntimeError("import request conflict cannot be resolved safely")
    return existing, False


async def claim_import(
    session: AsyncSession, tenant_id: uuid.UUID, *, lease_seconds: int = 900
) -> ImportClaim | None:
    if not 1 <= lease_seconds <= 3600:
        raise ValueError("invalid lease duration")
    request = (
        await session.execute(
            select(DossierImportRequest)
            .where(
                DossierImportRequest.tenant_id == tenant_id, DossierImportRequest.state == "pending"
            )
            .order_by(DossierImportRequest.created_at, DossierImportRequest.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if request is None:
        return None
    token = uuid.uuid4()
    request.state = "processing"
    request.lease_token = token
    request.lease_until = func.clock_timestamp() + timedelta(seconds=lease_seconds)
    request.attempts += 1
    request.updated_at = func.clock_timestamp()
    await session.flush()
    return ImportClaim(
        request.id,
        tenant_id,
        token,
        request.object_key,
        request.content_sha256,
        request.sync_config_id,
        request.requested_by,
        request.mapping_sha256,
    )


async def finish_import(
    session: AsyncSession,
    claim: ImportClaim,
    *,
    state: str,
    outcome_code: str,
    sync_log_id: uuid.UUID | None,
) -> None:
    """Fence finalization and force rollback if another owner or expiry wins."""
    if state not in {"completed", "failed", "uncertain"}:
        raise ValueError("invalid import outcome")
    if not re.fullmatch(r"[a-z0-9_]{1,64}", outcome_code):
        raise ValueError("invalid import outcome code")
    if state == "completed" and sync_log_id is None:
        raise ValueError("completed import requires a sync log")
    result = await session.execute(
        update(DossierImportRequest)
        .where(
            DossierImportRequest.id == claim.request_id,
            DossierImportRequest.tenant_id == claim.tenant_id,
            DossierImportRequest.object_key == claim.object_key,
            DossierImportRequest.content_sha256 == claim.content_sha256,
            DossierImportRequest.mapping_sha256 == claim.mapping_sha256,
            DossierImportRequest.sync_config_id == claim.sync_config_id,
            DossierImportRequest.requested_by == claim.requested_by,
            DossierImportRequest.state == "processing",
            DossierImportRequest.lease_token == claim.token,
            DossierImportRequest.lease_until > func.clock_timestamp(),
        )
        .values(
            state=state,
            outcome_code=outcome_code,
            sync_log_id=sync_log_id,
            lease_token=None,
            lease_until=None,
            updated_at=func.clock_timestamp(),
        )
    )
    if result.rowcount != 1:
        raise LostImportLeaseError("import lease is no longer current")


async def quarantine_expired_imports(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    result = await session.execute(
        update(DossierImportRequest)
        .where(
            DossierImportRequest.tenant_id == tenant_id,
            DossierImportRequest.state == "processing",
            DossierImportRequest.lease_until <= func.clock_timestamp(),
        )
        .values(
            state="uncertain",
            outcome_code="lease_expired",
            lease_token=None,
            lease_until=None,
            updated_at=func.clock_timestamp(),
        )
    )
    return int(result.rowcount)
