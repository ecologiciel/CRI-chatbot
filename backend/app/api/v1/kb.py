"""Knowledge Base management API — upload, list, get, delete, reindex.

All endpoints are tenant-scoped (resolved via X-Tenant-ID header by TenantMiddleware).
File uploads are stored in MinIO and processed asynchronously by the ARQ worker.
"""

from __future__ import annotations

import io
import uuid
from pathlib import PurePosixPath

import structlog
from fastapi import APIRouter, Depends, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.core.arq import get_arq_pool
from app.core.config import get_settings
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.minio import get_minio
from app.core.rbac import require_role
from app.core.tenant import TenantContext, get_current_tenant
from app.models.enums import AdminRole, KBDocumentStatus
from app.models.kb import KBDocument
from app.schemas.auth import AdminTokenPayload
from app.schemas.kb import (
    KBDocumentDetailResponse,
    KBDocumentList,
    KBDocumentResponse,
)

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


# ---------------------------------------------------------------------------
# Upload document
# ---------------------------------------------------------------------------


@router.post("/documents", status_code=202, response_model=KBDocumentResponse)
async def upload_document(
    file: UploadFile,
    title: str = Form(..., min_length=1, max_length=500),
    category: str | None = Form(default=None, max_length=100),
    language: str = Form(default="fr", pattern=r"^(fr|ar|en)$"),
    tenant: TenantContext = Depends(get_current_tenant),
    admin: AdminTokenPayload = Depends(require_role(AdminRole.super_admin, AdminRole.admin_tenant)),
) -> KBDocumentResponse:
    """Upload a file to the knowledge base.

    Stores the file in MinIO, creates a KBDocument record (status=pending),
    and enqueues an ARQ task for background ingestion.

    Returns 202 Accepted — the document will be processed asynchronously.
    """
    settings = get_settings()
    log = logger.bind(tenant=tenant.slug, admin_id=admin.sub, filename=file.filename)

    # 1. Validate extension
    ext = PurePosixPath(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            details={"extension": ext, "allowed": sorted(ALLOWED_EXTENSIONS)},
        )

    # 2. Read file and validate size
    file_bytes = await file.read()
    if len(file_bytes) > settings.kb_max_file_size_bytes:
        raise ValidationError(
            f"File too large: {len(file_bytes)} bytes (max {settings.kb_max_file_size_mb} MB)",
            details={
                "file_size": len(file_bytes),
                "max_size": settings.kb_max_file_size_bytes,
            },
        )

    # 3. Create KBDocument record in tenant DB
    doc_id = uuid.uuid4()
    file_path = f"kb/{doc_id}/{file.filename}"

    async with tenant.db_session() as session:
        doc = KBDocument(
            id=doc_id,
            title=title,
            category=category,
            language=language,
            file_path=file_path,
            file_size=len(file_bytes),
            status=KBDocumentStatus.pending,
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

    # 5. Enqueue ingestion task
    try:
        pool = get_arq_pool()
        await pool.enqueue_job(
            "ingest_document_task",
            tenant.slug,
            str(doc_id),
        )
        log.info("document_upload_enqueued", document_id=str(doc_id))
    except Exception as exc:
        log.warning("enqueue_failed", document_id=str(doc_id), error=str(exc))
        # Document is in DB + MinIO — admin can retry via /reindex

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

    # 1. Fetch document
    async with tenant.db_session() as session:
        result = await session.execute(select(KBDocument).where(KBDocument.id == document_id))
        doc = result.scalar_one_or_none()

    if doc is None:
        raise ResourceNotFoundError(
            f"Document not found: {document_id}",
            details={"document_id": str(document_id)},
        )

    file_path = doc.file_path

    # 2. Delete chunks from Qdrant + DB
    service = get_ingestion_service()
    await service.delete_document(tenant, document_id)

    # 3. Delete MinIO file (best-effort)
    if file_path:
        try:
            minio = get_minio()
            await minio.remove_object(tenant.minio_bucket, file_path)
        except Exception as exc:
            log.warning("minio_delete_failed", file_path=file_path, error=str(exc))

    # 4. Delete KBDocument record
    async with tenant.db_session() as session:
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

        # Reset status to pending
        doc.status = KBDocumentStatus.pending
        doc.error_message = None
        await session.flush()
        await session.refresh(doc)
        response = KBDocumentResponse.model_validate(doc)

    # Enqueue reindex task
    pool = get_arq_pool()
    await pool.enqueue_job(
        "reindex_document_task",
        tenant.slug,
        str(document_id),
    )
    log.info("reindex_enqueued")

    return response
