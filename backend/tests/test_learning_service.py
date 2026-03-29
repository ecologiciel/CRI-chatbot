"""Tests for SupervisedLearningService (Wave 15C).

Covers: imports, interface completeness, AI proposal generation,
approve/reject/edit workflow, stats, and deduplication.
No database required — uses mocks throughout.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import UnansweredStatus
from app.schemas.audit import AuditLogCreate
from app.schemas.feedback import UnansweredQuestionUpdate


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_question(**overrides):
    """Create a mock UnansweredQuestion with sensible defaults."""
    q = MagicMock()
    q.id = overrides.get("id", uuid.uuid4())
    q.question = overrides.get("question", "Comment créer une SARL au Maroc ?")
    q.language = overrides.get("language", "fr")
    q.frequency = overrides.get("frequency", 1)
    q.proposed_answer = overrides.get("proposed_answer", None)
    q.status = overrides.get("status", UnansweredStatus.pending)
    q.reviewed_by = overrides.get("reviewed_by", None)
    q.review_note = overrides.get("review_note", None)
    q.source_conversation_id = overrides.get("source_conversation_id", None)
    return q


def _make_mock_tenant(db_session_cm=None):
    """Create a MagicMock tenant that mimics TenantContext.

    TenantContext is a frozen dataclass with __slots__, so we cannot
    use patch.object on it. Instead we build a MagicMock with the
    same attributes and a configurable db_session context manager.
    """
    tenant = MagicMock()
    tenant.id = TEST_TENANT.id
    tenant.slug = "rabat"
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.whatsapp_config = None
    if db_session_cm is not None:
        tenant.db_session = db_session_cm
    return tenant


def _mock_session(scalars_return=None, scalar_one_or_none=None, scalar_one=None):
    """Build an async context manager mock for tenant.db_session().

    Args:
        scalars_return: Value for result.scalar_one_or_none().
        scalar_one_or_none: Alias (same as scalars_return).
        scalar_one: Value for result.scalar_one().
    """
    session = AsyncMock()
    execute_result = MagicMock()

    value = scalar_one_or_none if scalar_one_or_none is not None else scalars_return
    execute_result.scalar_one_or_none.return_value = value
    execute_result.scalar_one.return_value = scalar_one
    execute_result.one_or_none.return_value = None
    execute_result.all.return_value = []

    # For multiple sequential calls to session.execute(), we use side_effect
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def db_session():
        yield session

    return db_session, session, execute_result


def _make_retrieval_result(chunks=None, confidence=0.85):
    """Create a mock RetrievalResult."""
    if chunks is None:
        c1 = MagicMock(
            content="Pour créer une SARL, il faut...",
            metadata={"title": "Guide SARL"},
            score=0.9,
        )
        c2 = MagicMock(
            content="Les frais d'enregistrement sont...",
            metadata={"title": "Tarifs"},
            score=0.8,
        )
        chunks = [c1, c2]
    return MagicMock(chunks=chunks, confidence=confidence)


def _make_service(
    mock_feedback=None,
    mock_gemini=None,
    mock_retrieval=None,
    mock_embeddings=None,
    mock_audit=None,
):
    """Create SupervisedLearningService with mocked dependencies."""
    from app.services.learning.service import SupervisedLearningService

    feedback = mock_feedback or AsyncMock()
    gemini = mock_gemini or AsyncMock()
    retrieval = mock_retrieval or AsyncMock()
    embeddings = mock_embeddings or AsyncMock()
    audit = mock_audit or AsyncMock()

    service = SupervisedLearningService(
        feedback=feedback,
        gemini=gemini,
        retrieval=retrieval,
        embeddings=embeddings,
        audit=audit,
    )
    return service, feedback, gemini, retrieval, embeddings, audit


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestLearningImports:
    """Verify all learning modules are importable."""

    def test_service_import(self):
        from app.services.learning.service import SupervisedLearningService

        assert SupervisedLearningService is not None

    def test_singleton_factory_import(self):
        from app.services.learning.service import get_learning_service

        assert callable(get_learning_service)

    def test_package_reexport(self):
        from app.services.learning import (
            SupervisedLearningService,
            get_learning_service,
        )

        assert SupervisedLearningService is not None
        assert callable(get_learning_service)


# ---------------------------------------------------------------------------
# 2. Interface completeness
# ---------------------------------------------------------------------------


class TestServiceInterface:
    """Verify all required public methods and class attributes exist."""

    def test_has_generate_ai_proposal(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "generate_ai_proposal")

    def test_has_approve_question(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "approve_question")

    def test_has_reject_question(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "reject_question")

    def test_has_edit_proposal(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "edit_proposal")

    def test_has_get_unanswered_questions(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "get_unanswered_questions")

    def test_has_get_learning_stats(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "get_learning_stats")

    def test_has_deduplicate_question(self):
        from app.services.learning.service import SupervisedLearningService

        assert hasattr(SupervisedLearningService, "deduplicate_question")

    def test_similarity_threshold_valid(self):
        from app.services.learning.service import SupervisedLearningService

        assert 0 < SupervisedLearningService.SIMILARITY_THRESHOLD <= 1.0

    def test_similarity_threshold_default(self):
        from app.services.learning.service import SupervisedLearningService

        assert SupervisedLearningService.SIMILARITY_THRESHOLD == 0.85


# ---------------------------------------------------------------------------
# 3. UnansweredStatus enum completeness
# ---------------------------------------------------------------------------


class TestUnansweredStatusValues:
    """Verify the enum has all expected values."""

    def test_all_statuses_present(self):
        expected = {"pending", "approved", "modified", "rejected", "injected"}
        actual = {s.value for s in UnansweredStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 4. AI Proposal Generation
# ---------------------------------------------------------------------------


class TestGenerateAIProposal:
    """Tests for generate_ai_proposal()."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Retrieval returns chunks → Gemini generates → proposed_answer stored."""
        question = _make_question(status=UnansweredStatus.pending)
        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=question,
        )
        tenant = _make_mock_tenant(db_session_cm)

        retrieval_result = _make_retrieval_result()
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        gemini.generate_simple = AsyncMock(
            return_value="Pour créer une SARL au Maroc, vous devez...",
        )

        result = await service.generate_ai_proposal(tenant, question.id)

        # Verify retrieval was called with the question text
        retrieval.retrieve.assert_awaited_once()
        call_args = retrieval.retrieve.call_args
        assert call_args.args[0] is tenant
        assert call_args.kwargs.get("query") == question.question

        # Verify Gemini was called
        gemini.generate_simple.assert_awaited_once()

        # Verify proposed_answer was set
        assert question.proposed_answer == "Pour créer une SARL au Maroc, vous devez..."

        # Verify audit was logged
        audit.log_action.assert_awaited_once()
        audit_data = audit.log_action.call_args.args[0]
        assert isinstance(audit_data, AuditLogCreate)
        assert audit_data.action == "generate"
        assert audit_data.resource_type == "unanswered_question"

    @pytest.mark.asyncio
    async def test_question_not_found(self):
        """Non-existent question_id raises ResourceNotFoundError."""
        from app.core.exceptions import ResourceNotFoundError

        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=None,
        )
        tenant = _make_mock_tenant(db_session_cm)

        service, *_ = _make_service()

        with pytest.raises(ResourceNotFoundError):
            await service.generate_ai_proposal(tenant, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_wrong_status_raises(self):
        """Question with status != pending raises ValidationError."""
        from app.core.exceptions import ValidationError

        question = _make_question(status=UnansweredStatus.approved)
        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=question,
        )
        tenant = _make_mock_tenant(db_session_cm)

        service, *_ = _make_service()

        with pytest.raises(ValidationError, match="pending"):
            await service.generate_ai_proposal(tenant, question.id)

    @pytest.mark.asyncio
    async def test_empty_chunks_still_generates(self):
        """When retrieval returns no chunks, Gemini still generates with disclaimer."""
        question = _make_question(status=UnansweredStatus.pending)
        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=question,
        )
        tenant = _make_mock_tenant(db_session_cm)

        empty_result = MagicMock(chunks=[], confidence=0.0)
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        retrieval.retrieve = AsyncMock(return_value=empty_result)
        gemini.generate_simple = AsyncMock(
            return_value="Je n'ai pas trouvé d'information pertinente...",
        )

        result = await service.generate_ai_proposal(tenant, question.id)

        gemini.generate_simple.assert_awaited_once()
        # Verify the prompt mentions "Aucun document"
        prompt_arg = gemini.generate_simple.call_args.kwargs.get("prompt", "")
        assert "Aucun document" in prompt_arg


# ---------------------------------------------------------------------------
# 5. Approve question
# ---------------------------------------------------------------------------


class TestApproveQuestion:
    """Tests for approve_question()."""

    @pytest.mark.asyncio
    async def test_approve_with_override(self):
        """Approve with a provided answer → delegates to FeedbackService."""
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        returned_question = _make_question(status=UnansweredStatus.modified)
        feedback.update_unanswered_question = AsyncMock(
            return_value=returned_question,
        )

        admin_id = uuid.uuid4()
        result = await service.approve_question(
            TEST_TENANT,
            returned_question.id,
            admin_id,
            proposed_answer="Réponse modifiée par l'admin.",
        )

        # Verify FeedbackService was called with status=modified
        feedback.update_unanswered_question.assert_awaited_once()
        call_args = feedback.update_unanswered_question.call_args
        update_data: UnansweredQuestionUpdate = call_args.args[2]
        assert update_data.status == UnansweredStatus.modified
        assert update_data.proposed_answer == "Réponse modifiée par l'admin."

        # Verify audit
        audit.log_action.assert_awaited_once()
        audit_data = audit.log_action.call_args.args[0]
        assert audit_data.action == "approve"
        assert audit_data.user_id == admin_id

    @pytest.mark.asyncio
    async def test_approve_without_override_uses_existing(self):
        """Approve without override → reads existing proposed_answer from DB."""
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        question_id = uuid.uuid4()

        # Mock the DB read for existing proposed_answer
        db_session_cm, session, exec_result = _mock_session()
        exec_result.one_or_none.return_value = ("Réponse IA existante",)
        tenant = _make_mock_tenant(db_session_cm)

        returned_question = _make_question(
            id=question_id,
            status=UnansweredStatus.approved,
            proposed_answer="Réponse IA existante",
        )
        feedback.update_unanswered_question = AsyncMock(
            return_value=returned_question,
        )

        admin_id = uuid.uuid4()
        result = await service.approve_question(tenant, question_id, admin_id)

        # Verify FeedbackService was called with status=approved
        feedback.update_unanswered_question.assert_awaited_once()
        call_args = feedback.update_unanswered_question.call_args
        update_data: UnansweredQuestionUpdate = call_args.args[2]
        assert update_data.status == UnansweredStatus.approved

    @pytest.mark.asyncio
    async def test_approve_without_answer_raises(self):
        """Approve when no proposed_answer exists raises ValidationError."""
        from app.core.exceptions import ValidationError

        service, feedback, *_ = _make_service()

        question_id = uuid.uuid4()

        # DB returns question with no proposed_answer
        db_session_cm, session, exec_result = _mock_session()
        exec_result.one_or_none.return_value = (None,)
        tenant = _make_mock_tenant(db_session_cm)

        with pytest.raises(ValidationError, match="proposed answer"):
            await service.approve_question(tenant, question_id, uuid.uuid4())


# ---------------------------------------------------------------------------
# 6. Reject question
# ---------------------------------------------------------------------------


class TestRejectQuestion:
    """Tests for reject_question()."""

    @pytest.mark.asyncio
    async def test_reject_with_note(self):
        """Reject with review_note → delegates to FeedbackService."""
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        returned_question = _make_question(status=UnansweredStatus.rejected)
        feedback.update_unanswered_question = AsyncMock(
            return_value=returned_question,
        )

        admin_id = uuid.uuid4()
        result = await service.reject_question(
            TEST_TENANT,
            returned_question.id,
            admin_id,
            review_note="Question hors périmètre CRI.",
        )

        # Verify FeedbackService was called with status=rejected
        feedback.update_unanswered_question.assert_awaited_once()
        call_args = feedback.update_unanswered_question.call_args
        update_data: UnansweredQuestionUpdate = call_args.args[2]
        assert update_data.status == UnansweredStatus.rejected
        assert update_data.review_note == "Question hors périmètre CRI."

        # Verify audit
        audit.log_action.assert_awaited_once()
        audit_data = audit.log_action.call_args.args[0]
        assert audit_data.action == "reject"


# ---------------------------------------------------------------------------
# 7. Edit proposal
# ---------------------------------------------------------------------------


class TestEditProposal:
    """Tests for edit_proposal()."""

    @pytest.mark.asyncio
    async def test_edit_sets_modified_status(self):
        """Edit → delegates to FeedbackService with status=modified."""
        service, feedback, gemini, retrieval, embeddings, audit = _make_service()

        returned_question = _make_question(status=UnansweredStatus.modified)
        feedback.update_unanswered_question = AsyncMock(
            return_value=returned_question,
        )

        admin_id = uuid.uuid4()
        result = await service.edit_proposal(
            TEST_TENANT,
            returned_question.id,
            admin_id,
            proposed_answer="Réponse corrigée.",
            review_note="Correction de la formulation.",
        )

        feedback.update_unanswered_question.assert_awaited_once()
        call_args = feedback.update_unanswered_question.call_args
        update_data: UnansweredQuestionUpdate = call_args.args[2]
        assert update_data.status == UnansweredStatus.modified
        assert update_data.proposed_answer == "Réponse corrigée."
        assert update_data.review_note == "Correction de la formulation."

        # Verify audit
        audit.log_action.assert_awaited_once()
        audit_data = audit.log_action.call_args.args[0]
        assert audit_data.action == "edit"


# ---------------------------------------------------------------------------
# 8. Learning stats
# ---------------------------------------------------------------------------


class TestGetLearningStats:
    """Tests for get_learning_stats()."""

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self):
        """Stats dict has all expected keys with correct types."""
        service, *_ = _make_service()

        # Mock three sequential session.execute() calls:
        # 1. status counts, 2. avg review time, 3. top questions
        status_rows = [
            (UnansweredStatus.pending, 10),
            (UnansweredStatus.approved, 5),
            (UnansweredStatus.modified, 3),
            (UnansweredStatus.rejected, 2),
            (UnansweredStatus.injected, 1),
        ]
        avg_hours = 24.5
        top_rows = [
            MagicMock(id=uuid.uuid4(), question="Q1", frequency=8),
            MagicMock(id=uuid.uuid4(), question="Q2", frequency=5),
        ]

        # Build separate result mocks for each call
        status_exec = MagicMock()
        status_exec.all.return_value = status_rows

        avg_exec = MagicMock()
        avg_exec.scalar_one.return_value = avg_hours

        top_exec = MagicMock()
        top_exec.all.return_value = top_rows

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[status_exec, avg_exec, top_exec],
        )

        @asynccontextmanager
        async def db_session():
            yield session

        tenant = _make_mock_tenant(db_session)
        stats = await service.get_learning_stats(tenant)

        assert stats["total"] == 21  # 10+5+3+2+1
        assert stats["by_status"]["pending"] == 10
        assert stats["by_status"]["approved"] == 5
        assert stats["by_status"]["modified"] == 3
        assert stats["by_status"]["rejected"] == 2
        assert stats["by_status"]["injected"] == 1
        # approval_rate = (5+3) / (5+3+2) = 0.8
        assert stats["approval_rate"] == 0.8
        assert stats["avg_review_time_hours"] == 24.5
        assert len(stats["top_questions"]) == 2
        assert stats["top_questions"][0]["question"] == "Q1"
        assert stats["top_questions"][0]["frequency"] == 8


# ---------------------------------------------------------------------------
# 9. Deduplication
# ---------------------------------------------------------------------------


class TestDeduplicateQuestion:
    """Tests for deduplicate_question()."""

    @pytest.mark.asyncio
    async def test_exact_match_increments_frequency(self):
        """Existing pending question with same text → frequency incremented."""
        service, *_ = _make_service()

        existing = _make_question(frequency=3, status=UnansweredStatus.pending)
        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=existing,
        )
        tenant = _make_mock_tenant(db_session_cm)

        result = await service.deduplicate_question(
            tenant, "Comment créer une SARL au Maroc ?",
        )

        assert result is existing
        assert existing.frequency == 4  # was 3, incremented to 4

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        """No matching question → returns None."""
        service, *_ = _make_service()

        db_session_cm, session, exec_result = _mock_session(
            scalar_one_or_none=None,
        )
        tenant = _make_mock_tenant(db_session_cm)

        result = await service.deduplicate_question(
            tenant, "Quelle est la météo ?",
        )

        assert result is None


# ---------------------------------------------------------------------------
# 10. Cosine similarity helper
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """Tests for the _cosine_similarity static method."""

    def test_identical_vectors(self):
        from app.services.learning.service import SupervisedLearningService

        sim = SupervisedLearningService._cosine_similarity(
            [1.0, 0.0, 0.0], [1.0, 0.0, 0.0],
        )
        assert sim == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from app.services.learning.service import SupervisedLearningService

        sim = SupervisedLearningService._cosine_similarity(
            [1.0, 0.0], [0.0, 1.0],
        )
        assert sim == pytest.approx(0.0)

    def test_zero_vector(self):
        from app.services.learning.service import SupervisedLearningService

        sim = SupervisedLearningService._cosine_similarity(
            [0.0, 0.0], [1.0, 1.0],
        )
        assert sim == 0.0

    def test_similar_vectors(self):
        from app.services.learning.service import SupervisedLearningService

        sim = SupervisedLearningService._cosine_similarity(
            [1.0, 1.0, 0.0], [1.0, 1.0, 0.1],
        )
        assert sim > 0.9  # very similar


# ---------------------------------------------------------------------------
# 11. Prompt template validation
# ---------------------------------------------------------------------------


class TestPromptTemplate:
    """Verify the system prompt contains expected CRI context."""

    def test_prompt_mentions_cri(self):
        from app.services.learning.service import PROPOSAL_SYSTEM_PROMPT

        assert "CRI" in PROPOSAL_SYSTEM_PROMPT

    def test_prompt_mentions_validation(self):
        from app.services.learning.service import PROPOSAL_SYSTEM_PROMPT

        assert "validée" in PROPOSAL_SYSTEM_PROMPT or "validation" in PROPOSAL_SYSTEM_PROMPT

    def test_prompt_has_language_placeholder(self):
        from app.services.learning.service import PROPOSAL_SYSTEM_PROMPT

        assert "{language_name}" in PROPOSAL_SYSTEM_PROMPT
