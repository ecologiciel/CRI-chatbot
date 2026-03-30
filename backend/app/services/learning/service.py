"""SupervisedLearningService — AI-assisted supervised learning workflow.

Orchestrates the improvement cycle for the knowledge base:

1. COLLECT: Unanswered questions auto-flagged by the RAG pipeline (score < threshold)
   or by negative feedback (via FeedbackService, Phase 1).
2. PROPOSE: On admin request, Gemini generates a proposed answer using KB context.
3. VALIDATE: Admin approves, modifies, or rejects via back-office.
4. REINJECT: Approved Q&A pairs are reinjected into Qdrant (Wave 16 worker).

Conforms to CPS article 24, §1.2: "L'agent conversationnel IA devra intégrer un
mécanisme d'apprentissage supervisé comprenant la collecte des questions non reconnues,
la génération automatique de propositions de réponses, et une interface de validation
manuelle."
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

import structlog
from sqlalchemy import extract, func, select

from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.tenant import TenantContext
from app.models.enums import UnansweredStatus
from app.models.feedback import UnansweredQuestion
from app.schemas.audit import AuditLogCreate
from app.schemas.feedback import UnansweredQuestionUpdate
from app.services.ai.embeddings import EmbeddingService, get_embedding_service
from app.services.ai.gemini import GeminiService, get_gemini_service
from app.services.audit.service import AuditService, get_audit_service
from app.services.feedback.service import FeedbackService, get_feedback_service
from app.services.rag.retrieval import RetrievalService, get_retrieval_service

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prompt template for AI proposal generation
# ---------------------------------------------------------------------------

PROPOSAL_SYSTEM_PROMPT = """\
Tu es un expert des Centres Régionaux d'Investissement (CRI) du Maroc.
Un utilisateur a posé une question à laquelle le chatbot n'a pas pu répondre.
À partir des extraits de la base de connaissances fournis, génère une réponse
claire, précise et institutionnelle.

Règles :
- Réponds en {language_name}.
- Sois concis (2-4 phrases), factuel et utile.
- Si le contexte est insuffisant, indique-le clairement et propose une réponse
  basée sur tes connaissances générales des CRI, en précisant que c'est une
  suggestion à vérifier.
- La réponse sera validée par un agent CRI avant d'être ajoutée à la base de
  connaissances."""

LANGUAGE_NAMES = {"fr": "français", "ar": "arabe", "en": "anglais"}


class SupervisedLearningService:
    """AI-assisted supervised learning workflow for unanswered questions.

    Composes with FeedbackService for CRUD, GeminiService for AI generation,
    RetrievalService for KB context, EmbeddingService for similarity, and
    AuditService for the audit trail.

    Args:
        feedback: FeedbackService for UnansweredQuestion CRUD.
        gemini: GeminiService for generating proposed answers.
        retrieval: RetrievalService for RAG context retrieval.
        embeddings: EmbeddingService for semantic similarity.
        audit: AuditService for audit trail logging.
    """

    SIMILARITY_THRESHOLD: float = 0.85

    def __init__(
        self,
        feedback: FeedbackService,
        gemini: GeminiService,
        retrieval: RetrievalService,
        embeddings: EmbeddingService,
        audit: AuditService,
    ) -> None:
        self._feedback = feedback
        self._gemini = gemini
        self._retrieval = retrieval
        self._embeddings = embeddings
        self._audit = audit
        self._logger = logger.bind(service="learning")

    # ──────────────────────────────────────────────
    # LISTING & FILTERING
    # ──────────────────────────────────────────────

    async def get_unanswered_questions(
        self,
        tenant: TenantContext,
        *,
        status: UnansweredStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[UnansweredQuestion], int]:
        """List unanswered questions with optional filters and pagination.

        Extends FeedbackService listing with date-range filtering and
        frequency-descending ordering for the learning back-office page.

        Args:
            tenant: Tenant context for DB session.
            status: Filter by status (pending, approved, rejected, etc.).
            date_from: Start date filter (inclusive).
            date_to: End date filter (inclusive).
            page: Page number (1-indexed).
            page_size: Items per page.

        Returns:
            Tuple of (items, total_count).
        """
        async with tenant.db_session() as session:
            base = select(UnansweredQuestion)

            if status is not None:
                base = base.where(UnansweredQuestion.status == status)
            if date_from is not None:
                base = base.where(UnansweredQuestion.created_at >= date_from)
            if date_to is not None:
                base = base.where(UnansweredQuestion.created_at <= date_to)

            # Count
            count_result = await session.execute(
                select(func.count()).select_from(base.subquery()),
            )
            total = count_result.scalar_one()

            # Paginated data — most frequent first, then newest
            offset = (page - 1) * page_size
            data_result = await session.execute(
                base.order_by(
                    UnansweredQuestion.frequency.desc(),
                    UnansweredQuestion.created_at.desc(),
                )
                .offset(offset)
                .limit(page_size),
            )
            items = list(data_result.scalars().all())

        return items, total

    # ──────────────────────────────────────────────
    # AI PROPOSAL GENERATION
    # ──────────────────────────────────────────────

    async def generate_ai_proposal(
        self,
        tenant: TenantContext,
        question_id: uuid.UUID,
    ) -> UnansweredQuestion:
        """Generate an AI-proposed answer for an unanswered question.

        Pipeline:
        1. Fetch question from DB (raise if not found)
        2. Validate status is 'pending' (raise if not)
        3. Retrieve relevant KB chunks via RetrievalService
        4. Build prompt with chunk context
        5. Call GeminiService to generate a proposed answer
        6. Store proposed_answer in DB
        7. Log to audit trail

        The proposed answer is NOT sent to the user — it awaits human
        validation in the back-office.

        Args:
            tenant: Tenant context for all scoped operations.
            question_id: UUID of the unanswered question.

        Returns:
            Updated UnansweredQuestion with proposed_answer populated.

        Raises:
            ResourceNotFoundError: If question_id does not exist.
            ValidationError: If question is not in 'pending' status.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(UnansweredQuestion).where(
                    UnansweredQuestion.id == question_id,
                ),
            )
            question = result.scalar_one_or_none()
            if question is None:
                raise ResourceNotFoundError(
                    f"UnansweredQuestion {question_id} not found",
                )

            if question.status != UnansweredStatus.pending:
                raise ValidationError(
                    f"Cannot generate proposal: question status is "
                    f"'{question.status.value}', expected 'pending'",
                )

            # 1. Retrieve relevant KB chunks
            retrieval_result = await self._retrieval.retrieve(
                tenant,
                query=question.question,
                language=question.language,
            )

            # 2. Build prompt with chunk context
            if retrieval_result.chunks:
                chunks_text = "\n\n".join(
                    f"[Source : {c.metadata.get('title', 'Document')}]\n{c.content}"
                    for c in retrieval_result.chunks
                )
            else:
                chunks_text = "Aucun document pertinent trouvé dans la base de connaissances."

            language_name = LANGUAGE_NAMES.get(question.language, "français")
            system_prompt = PROPOSAL_SYSTEM_PROMPT.format(
                language_name=language_name,
            )

            user_prompt = (
                f'Question de l\'utilisateur :\n"{question.question}"\n\n'
                f"Contexte (extraits de la base de connaissances) :\n"
                f"{chunks_text}\n\n"
                f"Génère une réponse complète et institutionnelle :"
            )

            # 3. Call Gemini
            proposed_answer = await self._gemini.generate_simple(
                prompt=user_prompt,
                tenant=tenant,
                system_prompt=system_prompt,
            )

            # 4. Store the proposal
            question.proposed_answer = proposed_answer

            self._logger.info(
                "ai_proposal_generated",
                question_id=str(question_id),
                tenant=tenant.slug,
                answer_length=len(proposed_answer),
                chunks_used=len(retrieval_result.chunks),
            )

        # 5. Audit (fire-and-forget, outside DB session)
        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=None,
                user_type="system",
                action="generate",
                resource_type="unanswered_question",
                resource_id=str(question_id),
                details={"chunks_used": len(retrieval_result.chunks)},
            ),
        )

        return question

    # ──────────────────────────────────────────────
    # HUMAN VALIDATION (approve / reject / edit)
    # ──────────────────────────────────────────────

    async def approve_question(
        self,
        tenant: TenantContext,
        question_id: uuid.UUID,
        admin_id: uuid.UUID,
        proposed_answer: str | None = None,
    ) -> UnansweredQuestion:
        """Approve a question — marks it ready for Qdrant reinjection.

        If proposed_answer is provided, it overrides the existing one and
        status becomes 'modified'. Otherwise, the existing proposed_answer
        is used and status becomes 'approved'.

        Args:
            tenant: Tenant context.
            question_id: UUID of the question to approve.
            admin_id: UUID of the approving admin.
            proposed_answer: Optional override for the proposed answer.

        Returns:
            Updated UnansweredQuestion.

        Raises:
            ResourceNotFoundError: If question_id does not exist.
            ValidationError: If approving without a proposed_answer.
        """
        if proposed_answer is not None:
            # Admin edited the answer → modified
            data = UnansweredQuestionUpdate(
                status=UnansweredStatus.modified,
                proposed_answer=proposed_answer,
            )
        else:
            # Need to check that proposed_answer already exists.
            # FeedbackService will fetch + apply. The UnansweredQuestionUpdate
            # validator requires proposed_answer when status is 'approved',
            # so we must fetch it first.
            async with tenant.db_session() as session:
                result = await session.execute(
                    select(UnansweredQuestion.proposed_answer).where(
                        UnansweredQuestion.id == question_id,
                    ),
                )
                row = result.one_or_none()
                if row is None:
                    raise ResourceNotFoundError(
                        f"UnansweredQuestion {question_id} not found",
                    )
                existing_answer = row[0]
                if not existing_answer:
                    raise ValidationError(
                        "Cannot approve without a proposed answer. "
                        "Generate an AI proposal first or provide a manual answer.",
                    )

            data = UnansweredQuestionUpdate(
                status=UnansweredStatus.approved,
                proposed_answer=existing_answer,
            )

        question = await self._feedback.update_unanswered_question(
            tenant,
            question_id,
            data,
            admin_id,
        )

        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="approve",
                resource_type="unanswered_question",
                resource_id=str(question_id),
                details={
                    "status": question.status.value,
                    "had_edit": proposed_answer is not None,
                },
            ),
        )

        self._logger.info(
            "question_approved",
            question_id=str(question_id),
            status=question.status.value,
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )
        return question

    async def reject_question(
        self,
        tenant: TenantContext,
        question_id: uuid.UUID,
        admin_id: uuid.UUID,
        review_note: str | None = None,
    ) -> UnansweredQuestion:
        """Reject a question — it will not be reinjected.

        Args:
            tenant: Tenant context.
            question_id: UUID of the question to reject.
            admin_id: UUID of the rejecting admin.
            review_note: Optional reason for rejection.

        Returns:
            Updated UnansweredQuestion with status=rejected.

        Raises:
            ResourceNotFoundError: If question_id does not exist.
        """
        data = UnansweredQuestionUpdate(
            status=UnansweredStatus.rejected,
            review_note=review_note,
        )

        question = await self._feedback.update_unanswered_question(
            tenant,
            question_id,
            data,
            admin_id,
        )

        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="reject",
                resource_type="unanswered_question",
                resource_id=str(question_id),
                details={"reason": review_note},
            ),
        )

        self._logger.info(
            "question_rejected",
            question_id=str(question_id),
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )
        return question

    async def edit_proposal(
        self,
        tenant: TenantContext,
        question_id: uuid.UUID,
        admin_id: uuid.UUID,
        proposed_answer: str,
        review_note: str | None = None,
    ) -> UnansweredQuestion:
        """Edit the proposed answer and mark as modified (approved).

        The edited answer replaces any AI-generated proposal. Status becomes
        'modified' indicating human editing occurred. The question is ready
        for Qdrant reinjection.

        Args:
            tenant: Tenant context.
            question_id: UUID of the question.
            admin_id: UUID of the editing admin.
            proposed_answer: New answer text.
            review_note: Optional note about the edit.

        Returns:
            Updated UnansweredQuestion with status=modified.

        Raises:
            ResourceNotFoundError: If question_id does not exist.
        """
        data = UnansweredQuestionUpdate(
            status=UnansweredStatus.modified,
            proposed_answer=proposed_answer,
            review_note=review_note,
        )

        question = await self._feedback.update_unanswered_question(
            tenant,
            question_id,
            data,
            admin_id,
        )

        await self._audit.log_action(
            AuditLogCreate(
                tenant_slug=tenant.slug,
                user_id=admin_id,
                user_type="admin",
                action="edit",
                resource_type="unanswered_question",
                resource_id=str(question_id),
            ),
        )

        self._logger.info(
            "proposal_edited",
            question_id=str(question_id),
            admin_id=str(admin_id),
            tenant=tenant.slug,
        )
        return question

    # ──────────────────────────────────────────────
    # STATISTICS
    # ──────────────────────────────────────────────

    async def get_learning_stats(self, tenant: TenantContext) -> dict:
        """Get supervised learning statistics for the dashboard.

        Returns:
            Dict with:
            - total: total unanswered questions
            - by_status: {pending: N, approved: N, modified: N, rejected: N, injected: N}
            - approval_rate: (approved + modified) / (approved + modified + rejected)
            - avg_review_time_hours: avg hours between created_at and updated_at for reviewed
            - top_questions: top 5 pending questions by frequency
        """
        async with tenant.db_session() as session:
            # Counts by status
            status_result = await session.execute(
                select(
                    UnansweredQuestion.status,
                    func.count().label("cnt"),
                ).group_by(UnansweredQuestion.status),
            )
            by_status = {s.value: 0 for s in UnansweredStatus}
            for status, cnt in status_result.all():
                by_status[status.value] = cnt

            total = sum(by_status.values())

            # Approval rate
            approved = by_status["approved"] + by_status["modified"]
            rejected = by_status["rejected"]
            denominator = approved + rejected
            approval_rate = approved / denominator if denominator > 0 else 0.0

            # Avg review time (hours) for reviewed questions
            reviewed_statuses = [
                UnansweredStatus.approved,
                UnansweredStatus.modified,
                UnansweredStatus.rejected,
            ]
            avg_result = await session.execute(
                select(
                    func.avg(
                        extract(
                            "epoch",
                            UnansweredQuestion.updated_at - UnansweredQuestion.created_at,
                        )
                        / 3600.0,
                    ),
                ).where(UnansweredQuestion.status.in_(reviewed_statuses)),
            )
            avg_hours = avg_result.scalar_one()
            avg_review_time_hours = round(float(avg_hours), 2) if avg_hours is not None else None

            # Top 5 pending by frequency
            top_result = await session.execute(
                select(
                    UnansweredQuestion.id,
                    UnansweredQuestion.question,
                    UnansweredQuestion.frequency,
                )
                .where(UnansweredQuestion.status == UnansweredStatus.pending)
                .order_by(UnansweredQuestion.frequency.desc())
                .limit(5),
            )
            top_questions = [
                {
                    "id": str(row.id),
                    "question": row.question,
                    "frequency": row.frequency,
                }
                for row in top_result.all()
            ]

        return {
            "total": total,
            "by_status": by_status,
            "approval_rate": round(approval_rate, 4),
            "avg_review_time_hours": avg_review_time_hours,
            "top_questions": top_questions,
        }

    # ──────────────────────────────────────────────
    # DEDUPLICATION
    # ──────────────────────────────────────────────

    async def deduplicate_question(
        self,
        tenant: TenantContext,
        question_text: str,
    ) -> UnansweredQuestion | None:
        """Check if a similar pending question already exists.

        Uses case-insensitive exact match for Phase 2 (embedding-based
        similarity is a future enhancement). If found, increments the
        frequency counter instead of creating a duplicate.

        Args:
            tenant: Tenant context.
            question_text: The question to check for duplicates.

        Returns:
            The existing UnansweredQuestion if a duplicate was found (with
            frequency incremented), or None if no duplicate exists.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(UnansweredQuestion).where(
                    UnansweredQuestion.status == UnansweredStatus.pending,
                    func.lower(UnansweredQuestion.question) == func.lower(question_text),
                ),
            )
            match = result.scalar_one_or_none()

            if match is not None:
                match.frequency += 1
                self._logger.info(
                    "question_deduplicated",
                    question_id=str(match.id),
                    new_frequency=match.frequency,
                    tenant=tenant.slug,
                )
                return match

            return None

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Pure-Python implementation (no numpy dependency).
        Reserved for future embedding-based deduplication.

        Args:
            a: First vector.
            b: Second vector.

        Returns:
            Cosine similarity in [0, 1] (or 0.0 if either vector is zero).
        """
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_learning_service: SupervisedLearningService | None = None


def get_learning_service() -> SupervisedLearningService:
    """Get or create the SupervisedLearningService singleton."""
    global _learning_service  # noqa: PLW0603
    if _learning_service is None:
        _learning_service = SupervisedLearningService(
            feedback=get_feedback_service(),
            gemini=get_gemini_service(),
            retrieval=get_retrieval_service(),
            embeddings=get_embedding_service(),
            audit=get_audit_service(),
        )
    return _learning_service
