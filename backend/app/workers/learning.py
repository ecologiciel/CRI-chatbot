"""ARQ worker for supervised learning — Qdrant reinjection.

Runs as a separate process: arq app.workers.learning.WorkerSettings

Tasks:
    reinject_learning_task — embed approved Q&A, upsert to Qdrant, create KBChunk
"""

from __future__ import annotations

import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from qdrant_client.models import PointStruct
from sqlalchemy import func, select, text

from app.core.arq import LEARNING_QUEUE
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
            active_index_version=1,
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
    from app.services.guardrails.pii_masker import get_pii_masker

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

        if not question.reviewed_by:
            log.warning("missing_reviewer")
            return {"status": "missing_reviewer"}

        # Capture values before session closes
        q_text = question.question
        q_answer = question.proposed_answer
        q_language = question.language
        q_frequency = question.frequency
        q_reviewed_by = question.reviewed_by

    # 5. Format chunk content
    masker = get_pii_masker()
    safe_question = masker.mask(q_text).masked_text
    safe_answer = masker.mask(q_answer).masked_text
    chunk_content = f"Question : {safe_question}\n\nRéponse : {safe_answer}"

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
        "summary": f"Q&A validé: {safe_question[:100]}",
    }

    # 8. Single DB session for all mutations
    async with tenant.db_session() as session:
        # Serialize publications for the shared document and recheck the
        # question after embedding so duplicate jobs cannot publish twice.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"supervised-learning:{tenant_slug}"},
        )
        locked = await session.execute(
            select(UnansweredQuestion)
            .where(UnansweredQuestion.id == uuid_lib.UUID(question_id))
            .with_for_update()
        )
        current = locked.scalar_one_or_none()
        if not current or current.status == UnansweredStatus.injected:
            return {"status": "already_injected"}
        if (
            current.status not in (UnansweredStatus.approved, UnansweredStatus.modified)
            or current.question != q_text
            or current.proposed_answer != q_answer
            or current.reviewed_by != q_reviewed_by
        ):
            log.warning("question_changed_before_publication")
            return {"status": "question_changed"}
        # Get or create synthetic document
        learning_doc = await _get_or_create_learning_document(
            session,
            tenant_slug,
        )
        if learning_doc.status != KBDocumentStatus.indexed:
            raise ValueError("Supervised learning document is not publishable")
        if learning_doc.active_index_version is None:
            learning_doc.active_index_version = 1
        if learning_doc.validated_by is None:
            learning_doc.validated_by = q_reviewed_by
            learning_doc.validated_at = datetime.now(UTC)
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
            index_version=learning_doc.active_index_version,
            qdrant_point_id=qdrant_point_id,
            token_count=len(chunk_content.split()),
            metadata_={
                "source": "supervised_learning",
                "question_id": question_id,
                "original_question": safe_question[:500],
            },
        )
        session.add(chunk)

        # Update question status to injected
        current.status = UnansweredStatus.injected

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


async def recover_approved_questions(ctx: dict) -> int:
    """Requeue reviewed answers stranded by an interrupted enqueue or worker."""
    from app.core.database import get_session_factory
    from app.core.tenant import TenantResolver
    from app.models.enums import TenantStatus
    from app.models.tenant import Tenant

    async with get_session_factory()() as session:
        result = await session.execute(
            select(Tenant.slug).where(Tenant.status == TenantStatus.active)
        )
        slugs = result.scalars().all()
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    queued = 0
    for slug in slugs:
        try:
            tenant = await TenantResolver.from_slug(slug)
            async with tenant.db_session() as session:
                result = await session.execute(
                    select(UnansweredQuestion.id, UnansweredQuestion.updated_at)
                    .where(
                        UnansweredQuestion.status.in_(
                            [UnansweredStatus.approved, UnansweredStatus.modified]
                        ),
                        UnansweredQuestion.reviewed_by.is_not(None),
                        UnansweredQuestion.proposed_answer.is_not(None),
                        UnansweredQuestion.updated_at < cutoff,
                    )
                    .order_by(UnansweredQuestion.updated_at)
                    .limit(100)
                )
                candidates = result.all()
            for question_id, updated_at in candidates:
                stamp = int(updated_at.timestamp() * 1_000_000)
                job = await ctx["redis"].enqueue_job(
                    "reinject_learning_task",
                    slug,
                    str(question_id),
                    _queue_name=LEARNING_QUEUE,
                    _job_id=f"learning-recovery:{slug}:{question_id}:{stamp}",
                )
                queued += int(job is not None)
        except Exception as exc:
            logger.warning(
                "learning_recovery_tenant_failed", tenant=slug, error_type=type(exc).__name__
            )
    logger.info("learning_recovery_complete", queued=queued)
    return queued


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
    queue_name = LEARNING_QUEUE
    cron_jobs = [cron(recover_approved_questions, minute={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _get_redis_settings()
    max_jobs = 5
    job_timeout = 120  # 2 minutes (embed + upsert, much faster than ingestion)
    max_tries = 3
