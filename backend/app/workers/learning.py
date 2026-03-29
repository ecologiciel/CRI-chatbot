"""ARQ worker for supervised learning — Qdrant reinjection.

Runs as a separate process: arq app.workers.learning.WorkerSettings

Tasks:
    reinject_learning_task — embed approved Q&A, upsert to Qdrant, create KBChunk
"""

from __future__ import annotations

import uuid as uuid_lib

import structlog
from arq.connections import RedisSettings
from qdrant_client.models import PointStruct
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.enums import KBDocumentStatus, UnansweredStatus
from app.models.feedback import UnansweredQuestion
from app.models.kb import KBChunk, KBDocument
from app.schemas.audit import AuditLogCreate

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEARNING_DOC_TITLE = "Apprentissage supervisé"
LEARNING_DOC_SOURCE = "learning://supervised"


# ---------------------------------------------------------------------------
# Lifecycle hooks (called by ARQ)
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialize infrastructure for the learning worker process."""
    from app.core.database import get_engine
    from app.core.logging import setup_logging
    from app.core.qdrant import init_qdrant
    from app.core.redis import init_redis

    setup_logging()
    get_engine()
    await init_redis()
    await init_qdrant()
    logger.info("learning_worker_started")


async def shutdown(ctx: dict) -> None:
    """Clean up connections on worker stop."""
    from app.core.database import close_engine
    from app.core.qdrant import close_qdrant
    from app.core.redis import close_redis

    await close_qdrant()
    await close_redis()
    await close_engine()
    logger.info("learning_worker_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_or_create_learning_document(session, tenant_slug: str) -> KBDocument:
    """Get or create the synthetic KBDocument for supervised learning chunks.

    Each tenant gets exactly one document with source_url='learning://supervised'.
    All learning-injected chunks attach to this document, preserving FK integrity
    on the KBChunk.document_id (non-nullable) column.

    Args:
        session: Active tenant-scoped DB session.
        tenant_slug: Tenant slug (for logging only).

    Returns:
        The existing or newly created KBDocument.
    """
    result = await session.execute(
        select(KBDocument).where(
            KBDocument.source_url == LEARNING_DOC_SOURCE,
        ),
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        doc = KBDocument(
            title=LEARNING_DOC_TITLE,
            source_url=LEARNING_DOC_SOURCE,
            category="learning",
            language="fr",
            status=KBDocumentStatus.indexed,
            chunk_count=0,
        )
        session.add(doc)
        await session.flush()  # Get doc.id before creating chunks
        logger.info(
            "learning_document_created",
            document_id=str(doc.id),
            tenant=tenant_slug,
        )

    return doc


async def _next_chunk_index(session, document_id: uuid_lib.UUID) -> int:
    """Compute the next chunk_index for a given document.

    Args:
        session: Active tenant-scoped DB session.
        document_id: UUID of the parent KBDocument.

    Returns:
        Next chunk_index (0 if no chunks exist yet).
    """
    result = await session.execute(
        select(func.coalesce(func.max(KBChunk.chunk_index), -1) + 1).where(
            KBChunk.document_id == document_id,
        ),
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


async def reinject_learning_task(
    ctx: dict,
    tenant_slug: str,
    question_id: str,
) -> dict:
    """Reinject an approved question into Qdrant as a searchable KB chunk.

    Pipeline:
    1. Resolve tenant context from slug.
    2. Fetch UnansweredQuestion from tenant DB.
    3. Idempotency guard: skip if already injected.
    4. Validate status is approved/modified and answer exists.
    5. Format chunk content: 'Question : ... Réponse : ...'
    6. Generate 768-dim embedding via EmbeddingService.
    7. Upsert point to Qdrant (before DB commit for safety).
    8. In a single DB session: create KBChunk, update question status,
       increment synthetic document chunk_count.
    9. Fire-and-forget audit log.

    The task is idempotent: if the question is already in 'injected' status,
    it returns immediately without error.

    Args:
        ctx: ARQ context dict.
        tenant_slug: Slug of the tenant.
        question_id: UUID string of the UnansweredQuestion.

    Returns:
        Dict with status and details (qdrant_point_id on success).
    """
    from app.core.qdrant import get_qdrant
    from app.core.tenant import TenantResolver
    from app.services.ai.embeddings import get_embedding_service
    from app.services.audit.service import get_audit_service

    log = logger.bind(
        task="reinject_learning",
        tenant=tenant_slug,
        question_id=question_id,
    )

    # 1. Resolve tenant
    tenant = await TenantResolver.from_slug(tenant_slug)

    # 2. Fetch question and validate
    async with tenant.db_session() as session:
        result = await session.execute(
            select(UnansweredQuestion).where(
                UnansweredQuestion.id == uuid_lib.UUID(question_id),
            ),
        )
        question = result.scalar_one_or_none()

        if question is None:
            log.warning("question_not_found")
            return {"status": "not_found"}

        # 3. Idempotency guard
        if question.status == UnansweredStatus.injected:
            log.info("question_already_injected")
            return {"status": "already_injected"}

        # 4. Validate status
        if question.status not in (
            UnansweredStatus.approved,
            UnansweredStatus.modified,
        ):
            log.warning("invalid_status", status=question.status.value)
            return {
                "status": "invalid_status",
                "reason": question.status.value,
            }

        if not question.proposed_answer:
            log.error("no_proposed_answer")
            return {"status": "no_answer"}

        # Capture values before session closes
        q_text = question.question
        q_answer = question.proposed_answer
        q_language = question.language
        q_frequency = question.frequency
        q_reviewed_by = question.reviewed_by

    # 5. Format chunk content
    chunk_content = f"Question : {q_text}\n\nRéponse : {q_answer}"

    # 6. Generate embedding
    embedding_service = get_embedding_service()
    embedding = await embedding_service.embed_single(
        chunk_content,
        tenant,
        task_type="RETRIEVAL_DOCUMENT",
    )

    # 7. Prepare Qdrant point
    qdrant_point_id = str(uuid_lib.uuid4())
    qdrant = get_qdrant()

    payload = {
        "document_id": "",  # Will be set after get_or_create
        "chunk_index": 0,  # Will be set after computing next index
        "content": chunk_content[:2000],
        "title": LEARNING_DOC_TITLE,
        "language": q_language,
        "source": "supervised_learning",
        "question_id": question_id,
        "related_laws": [],
        "applicable_sectors": [],
        "legal_forms": [],
        "regions": [],
        "summary": f"Q&A validé: {q_text[:100]}",
    }

    # 8. Single DB session for all mutations
    async with tenant.db_session() as session:
        # Get or create synthetic document
        learning_doc = await _get_or_create_learning_document(
            session, tenant_slug,
        )
        next_index = await _next_chunk_index(session, learning_doc.id)

        # Finalize payload with actual values
        payload["document_id"] = str(learning_doc.id)
        payload["chunk_index"] = next_index

        # Upsert to Qdrant BEFORE DB commit
        point = PointStruct(
            id=qdrant_point_id,
            vector=embedding,
            payload=payload,
        )
        await qdrant.upsert(
            collection_name=tenant.qdrant_collection,
            points=[point],
        )

        # Create KBChunk record
        chunk = KBChunk(
            document_id=learning_doc.id,
            content=chunk_content,
            chunk_index=next_index,
            qdrant_point_id=qdrant_point_id,
            token_count=len(chunk_content.split()),
            metadata_={
                "source": "supervised_learning",
                "question_id": question_id,
                "original_question": q_text[:500],
            },
        )
        session.add(chunk)

        # Update question status to injected
        q_result = await session.execute(
            select(UnansweredQuestion).where(
                UnansweredQuestion.id == uuid_lib.UUID(question_id),
            ),
        )
        question = q_result.scalar_one()
        question.status = UnansweredStatus.injected

        # Increment synthetic document chunk count
        learning_doc.chunk_count += 1

        # Session auto-commits on context manager exit

    # 9. Audit log (fire-and-forget)
    audit = get_audit_service()
    await audit.log_action(
        AuditLogCreate(
            tenant_slug=tenant_slug,
            user_id=q_reviewed_by,
            user_type="admin",
            action="reinject_qdrant",
            resource_type="unanswered_question",
            resource_id=question_id,
            details={
                "qdrant_point_id": qdrant_point_id,
                "chunk_index": next_index,
                "frequency": q_frequency,
            },
        ),
    )

    log.info(
        "question_injected",
        qdrant_point_id=qdrant_point_id,
        chunk_index=next_index,
    )

    return {
        "status": "ok",
        "qdrant_point_id": qdrant_point_id,
        "chunk_index": next_index,
    }


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — entry point for `arq app.workers.learning.WorkerSettings`
# ---------------------------------------------------------------------------


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from app config."""
    settings = get_settings()
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )


class WorkerSettings:
    """ARQ worker configuration for supervised learning reinjection."""

    functions = [reinject_learning_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 5
    job_timeout = 120  # 2 minutes (embed + upsert, much faster than ingestion)
    max_tries = 3
