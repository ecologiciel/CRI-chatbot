"""Knowledge Base management API — upload, list, get, delete, reindex.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
File uploads are stored in MinIO and processed asynchronously by the ARQ worker.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from pathlib import PurePosixPath

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import selectinload

from app.core.arq import get_arq_pool
from app.core.config import get_settings
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.minio import get_minio
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.core.uploads import validate_docx_archive, validate_upload_filename
from app.models.enums import AdminRole, KBDocumentStatus
from app.models.kb import KBDocument
from app.schemas.auth import AdminTokenPayload
from app.schemas.kb import (
    KBDocumentDetailResponse,
    KBDocumentList,
    KBDocumentResponse,
    KBDocumentValidationRequest,
)
from app.services.antivirus import AntivirusUnavailableError, MalwareDetectedError, scan_document
from app.services.rag.publication_policy import ensure_publishable as _ensure_publishable
from app.services.rag.publication_policy import ensure_validated as _ensure_reindexable

logger = structlog.get_logger()

router = APIRouter(prefix="/kb", tags=["knowledge-base"])

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt", ".md", ".csv"}

CONTENT_TYPE_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


def _validate_file_signature(extension: str, file_bytes: bytes) -> None:
    """Reject mismatched or binary textual uploads before object storage."""
    if extension == ".pdf" and not file_bytes.startswith(b"%PDF-"):
        raise ValidationError("Le contenu ne correspond pas à un PDF valide.")
    if extension == ".docx" and not file_bytes.startswith(b"PK\x03\x04"):
        raise ValidationError("Le contenu ne correspond pas à un DOCX valide.")
    if extension in {".txt", ".md", ".csv"} and b"\x00" in file_bytes:
        raise ValidationError("Un document texte ne peut pas contenir de données binaires.")


async def _enqueue_ingestion(tenant: TenantContext, document_id: uuid.UUID, task: str) -> None:
    """Expose enqueue failures and avoid leaving a document silently pending."""
    try:
        pool = get_arq_pool()
        await pool.enqueue_job(task, tenant.slug, str(document_id))
    except Exception as exc:
        logger.error(
            "ingestion_enqueue_failed",
            tenant=tenant.slug,
            document_id=str(document_id),
            error_type=type(exc).__name__,
        )
        async with tenant.db_session() as session:
            await session.execute(
                update(KBDocument)
                .where(KBDocument.id == document_id, KBDocument.status == KBDocumentStatus.pending)
                .values(
                    status=KBDocumentStatus.error,
                    error_message="Impossible de placer le document en file de traitement. Réessayez.",
                )
            )
        raise HTTPException(
            status_code=503, detail="Service d’indexation indisponible. Réessayez."
        ) from exc


# ---------------------------------------------------------------------------
# Upload document
# ---------------------------------------------------------------------------


@router.post("/documents", status_code=202, response_model=KBDocumentResponse)
async def upload_document(
    file: UploadFile,
    title: str = Form(..., min_length=1, max_length=500),
    category: str | None = Form(default=None, max_length=100),
    language: str = Form(default="fr", pattern=r"^(fr|ar|en)$"),
    source_url: str | None = Form(default=None, max_length=1000),
    source_authority: str | None = Form(default=None, max_length=300),
    source_reference: str | None = Form(default=None, max_length=500),
    source_version: str | None = Form(default=None, max_length=100),
    published_at: date | None = Form(default=None),
    expires_at: date | None = Form(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> KBDocumentResponse:
    """Upload a file to the knowledge base.

    Stores the file in MinIO and creates a quarantined document. A human
    validator must approve provenance metadata before ingestion is enqueued.

    Returns 202 Accepted — the document will be processed asynchronously.
    """
    settings = get_settings()
    # 1. Validate extension
    filename = validate_upload_filename(file.filename)
    ext = PurePosixPath(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            details={"extension": ext, "allowed": sorted(ALLOWED_EXTENSIONS)},
        )

    # 2. Read file and validate size
    file_bytes = await file.read(settings.kb_max_file_size_bytes + 1)
    if len(file_bytes) > settings.kb_max_file_size_bytes:
        raise ValidationError(
            f"File too large (max {settings.kb_max_file_size_mb} MB)",
            details={
                "file_size_at_least": len(file_bytes),
                "max_size": settings.kb_max_file_size_bytes,
            },
        )
    _validate_file_signature(ext, file_bytes)
    if ext == ".docx":
        validate_docx_archive(file_bytes)
    try:
        await scan_document(file_bytes)
    except MalwareDetectedError as exc:
        raise HTTPException(
            status_code=422, detail="Document refusé par le contrôle antivirus."
        ) from exc
    except AntivirusUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Contrôle antivirus indisponible. Réessayez."
        ) from exc

    # 3. Create KBDocument record in tenant DB
    doc_id = uuid.uuid4()
    file_path = f"kb/{doc_id}/{filename}"

    async with tenant.db_session() as session:
        doc = KBDocument(
            id=doc_id,
            title=title,
            category=category,
            language=language,
            source_url=source_url,
            source_authority=source_authority,
            source_reference=source_reference,
            source_version=source_version,
            published_at=published_at,
            expires_at=expires_at,
            file_path=file_path,
            file_size=len(file_bytes),
            status=KBDocumentStatus.pending_validation,
        )
        session.add(doc)
        await session.flush()

        # 4. Upload to MinIO
        content_type = CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
        minio = get_minio()
        await minio.put_object(
            bucket_name=tenant.minio_bucket,
            object_name=file_path,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )

        # Refresh to get server defaults (timestamps)
        await session.refresh(doc)
        response = KBDocumentResponse.model_validate(doc)

    return response


@router.post(
    "/documents/{document_id}/validate",
    status_code=202,
    response_model=KBDocumentResponse,
)
async def validate_document(
    document_id: uuid.UUID,
    data: KBDocumentValidationRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> KBDocumentResponse:
    """Approve source evidence and enqueue an otherwise quarantined document."""
    async with tenant.db_session() as session:
        result = await session.execute(select(KBDocument).where(KBDocument.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            raise ResourceNotFoundError("Document introuvable.")
        if document.status not in {KBDocumentStatus.pending_validation, KBDocumentStatus.rejected}:
            raise ValidationError("Seul un document en attente de validation peut être publié.")

        document.source_authority = data.source_authority
        document.source_reference = data.source_reference
        document.source_version = data.source_version
        document.source_url = data.source_url
        document.published_at = data.published_at
        document.expires_at = data.expires_at
        document.verified_at = datetime.now(UTC)
        document.validated_at = datetime.now(UTC)
        document.validated_by = uuid.UUID(str(admin.sub))
        _ensure_publishable(document)
        document.status = KBDocumentStatus.pending
        document.error_message = None
        await session.flush()
        await session.refresh(document)
        response = KBDocumentResponse.model_validate(document)

    await _enqueue_ingestion(tenant, document_id, "ingest_document_task")
    logger.info("document_validated_and_enqueued", tenant=tenant.slug, document_id=str(document_id))
    return response


# ---------------------------------------------------------------------------
# List documents
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=KBDocumentList)
async def list_documents(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        )
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: KBDocumentStatus | None = Query(default=None, description="Filter by status"),
    category: str | None = Query(default=None, description="Filter by category"),
) -> KBDocumentList:
    """List KB documents with pagination and optional filters."""
    async with tenant.db_session() as session:
        # Count query
        count_stmt = select(func.count(KBDocument.id))
        if status is not None:
            count_stmt = count_stmt.where(KBDocument.status == status)
        if category is not None:
            count_stmt = count_stmt.where(KBDocument.category == category)
        total = (await session.execute(count_stmt)).scalar_one()

        # Data query
        data_stmt = select(KBDocument).order_by(KBDocument.created_at.desc())
        if status is not None:
            data_stmt = data_stmt.where(KBDocument.status == status)
        if category is not None:
            data_stmt = data_stmt.where(KBDocument.category == category)
        data_stmt = data_stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(data_stmt)
        documents = result.scalars().all()

    return KBDocumentList(
        items=[KBDocumentResponse.model_validate(d) for d in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Get document detail
# ---------------------------------------------------------------------------


@router.get("/documents/categories", response_model=list[str])
async def list_document_categories(
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        )
    ),
) -> list[str]:
    """List categories from all documents in the selected tenant."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(KBDocument.category)
            .where(KBDocument.category.is_not(None), KBDocument.category != "")
            .distinct()
            .order_by(KBDocument.category)
        )
        return [value for value in result.scalars().all() if value is not None]


@router.get("/documents/{document_id}", response_model=KBDocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(
        require_role(
            AdminRole.super_admin,
            AdminRole.admin_tenant,
            AdminRole.supervisor,
            AdminRole.viewer,
        )
    ),
) -> KBDocumentDetailResponse:
    """Get document details including its chunks."""
    async with tenant.db_session() as session:
        result = await session.execute(
            select(KBDocument)
            .where(KBDocument.id == document_id)
            .options(selectinload(KBDocument.chunks))
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        raise ResourceNotFoundError(
            f"Document not found: {document_id}",
            details={"document_id": str(document_id)},
        )

    return KBDocumentDetailResponse.model_validate(doc)


# ---------------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------------


@router.delete("/documents/{document_id}", status_code=204, response_class=Response)
async def delete_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> Response:
    """Delete a document, its chunks (DB + Qdrant), and MinIO file."""
    from app.services.rag.ingestion import get_ingestion_service

    log = logger.bind(tenant=tenant.slug, document_id=str(document_id), admin_id=admin.sub)

    # Hold the same transaction-scoped lock as ingestion until the document
    # record is deleted. Otherwise a concurrent worker can republish points
    # between the Qdrant cleanup and deletion of the document.
    async with tenant.db_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"kb:{tenant.id}:{document_id}"},
        )
        result = await session.execute(select(KBDocument).where(KBDocument.id == document_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            raise ResourceNotFoundError(
                f"Document not found: {document_id}",
                details={"document_id": str(document_id)},
            )

        file_path = doc.file_path
        service = get_ingestion_service()
        await service.delete_document(tenant, document_id)

        if file_path:
            try:
                minio = get_minio()
                await minio.remove_object(tenant.minio_bucket, file_path)
            except Exception as exc:
                log.warning("minio_delete_failed", file_path=file_path, error=str(exc))

        await session.execute(delete(KBDocument).where(KBDocument.id == document_id))

    log.info("document_deleted")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Reindex document
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/reindex",
    status_code=202,
    response_model=KBDocumentResponse,
)
async def reindex_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> KBDocumentResponse:
    """Re-process a document: delete existing chunks and re-ingest.

    The document must have a file_path (uploaded via the upload endpoint).
    Returns 202 — reindexing happens asynchronously.
    """
    log = logger.bind(tenant=tenant.slug, document_id=str(document_id), admin_id=admin.sub)

    async with tenant.db_session() as session:
        result = await session.execute(select(KBDocument).where(KBDocument.id == document_id))
        doc = result.scalar_one_or_none()

        if doc is None:
            raise ResourceNotFoundError(
                f"Document not found: {document_id}",
                details={"document_id": str(document_id)},
            )

        if not doc.file_path:
            raise ValidationError(
                "Cannot reindex a document without a file",
                details={"document_id": str(document_id)},
            )

        _ensure_reindexable(doc)

        # Reset status to pending
        doc.status = KBDocumentStatus.pending
        doc.error_message = None
        await session.flush()
        await session.refresh(doc)
        response = KBDocumentResponse.model_validate(doc)

    # Enqueue reindex task
    await _enqueue_ingestion(tenant, document_id, "reindex_document_task")
    log.info("reindex_enqueued")

    return response
