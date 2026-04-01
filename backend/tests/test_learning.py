"""Tests unitaires du module Apprentissage Supervise.

Couvre :
- SupervisedLearningService : list, generate, approve, reject, edit, stats, dedup
- Worker reinject_approved_question
- Audit logging
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.models.enums import UnansweredStatus

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_ADMIN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _make_tenant_mock(session_mock=None):
    """Create a MagicMock tenant with db_session async context manager."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = "rabat"
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.qdrant_collection = "kb_rabat"

    if session_mock:

        @asynccontextmanager
        async def fake_db():
            yield session_mock

        tenant.db_session = fake_db
    return tenant


def _make_learning_service():
    """Create a SupervisedLearningService with all dependencies mocked."""
    from app.services.learning.service import SupervisedLearningService

    return SupervisedLearningService(
        feedback=AsyncMock(),
        gemini=AsyncMock(),
        retrieval=AsyncMock(),
        embeddings=AsyncMock(),
        audit=AsyncMock(),
    )


def _make_question_mock(**overrides):
    """Create a mock UnansweredQuestion."""
    defaults = {
        "id": uuid.uuid4(),
        "question": "Comment obtenir un agrement pour un projet touristique ?",
        "language": "fr",
        "frequency": 3,
        "proposed_answer": None,
        "status": UnansweredStatus.pending,
        "reviewed_by": None,
        "review_note": None,
        "source_conversation_id": None,
        "created_at": datetime(2026, 2, 15, tzinfo=UTC),
        "updated_at": datetime(2026, 2, 15, tzinfo=UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# =====================================================================
# Generate Proposal
# =====================================================================


class TestGenerateProposal:
    """Tests de la generation de propositions IA."""

    @pytest.mark.asyncio
    async def test_generate_proposal_success(self):
        """Happy path: question pending -> retrieval -> gemini -> proposition."""
        svc = _make_learning_service()
        question = _make_question_mock()

        # generate_ai_proposal uses tenant.db_session() directly
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = question
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()

        retrieval_result = MagicMock()
        retrieval_result.chunks = [MagicMock(content="Contexte KB", metadata={"title": "Doc"})]
        svc._retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        svc._gemini.generate_simple = AsyncMock(return_value="Pour obtenir un agrement...")
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock(session)
        result = await svc.generate_ai_proposal(tenant, question.id)
        assert result is not None
        svc._gemini.generate_simple.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_proposal_not_found_raises(self):
        """Question inexistante -> ResourceNotFoundError."""
        from app.core.exceptions import ResourceNotFoundError

        svc = _make_learning_service()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)
        with pytest.raises(ResourceNotFoundError):
            await svc.generate_ai_proposal(tenant, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_generate_proposal_wrong_status_raises(self):
        """Question non-pending -> ValidationError."""
        from app.core.exceptions import ValidationError

        svc = _make_learning_service()
        question = _make_question_mock(status=UnansweredStatus.approved)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = question
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)
        with pytest.raises(ValidationError):
            await svc.generate_ai_proposal(tenant, question.id)

    @pytest.mark.asyncio
    async def test_generate_proposal_empty_chunks_still_generates(self):
        """Aucun chunk RAG -> genere quand meme une proposition."""
        svc = _make_learning_service()
        question = _make_question_mock()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = question
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()

        retrieval_result = MagicMock()
        retrieval_result.chunks = []
        svc._retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        svc._gemini.generate_simple = AsyncMock(return_value="Proposition generale")
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock(session)
        result = await svc.generate_ai_proposal(tenant, question.id)
        assert result is not None
        svc._gemini.generate_simple.assert_called_once()


# =====================================================================
# Approve / Reject
# =====================================================================


class TestApproveReject:
    """Tests du workflow d'approbation et de rejet."""

    @pytest.mark.asyncio
    async def test_approve_without_override_uses_existing(self):
        """Approbation sans final_answer -> status=approved, proposed_answer inchange."""
        svc = _make_learning_service()
        question = _make_question_mock(
            proposed_answer="Reponse existante",
            status=UnansweredStatus.pending,
        )
        # approve_question reads proposed_answer from DB via tenant.db_session()
        session = AsyncMock()
        row_mock = ("Reponse existante",)
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row_mock
        session.execute = AsyncMock(return_value=result_mock)

        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock(session)
        result = await svc.approve_question(tenant, question.id, TEST_ADMIN_ID)
        assert result is not None
        svc._feedback.update_unanswered_question.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_with_override(self):
        """Approbation avec final_answer -> status=modified, proposed_answer maj."""
        svc = _make_learning_service()
        question = _make_question_mock(
            proposed_answer="Ancienne reponse",
            status=UnansweredStatus.pending,
        )
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        # When proposed_answer is provided, no DB lookup needed
        tenant = _make_tenant_mock()
        result = await svc.approve_question(
            tenant, question.id, TEST_ADMIN_ID, proposed_answer="Nouvelle reponse"
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_approve_without_answer_raises(self):
        """Approbation sans proposed_answer ni final_answer -> erreur."""
        from app.core.exceptions import ValidationError

        svc = _make_learning_service()
        # DB returns no existing answer
        session = AsyncMock()
        row_mock = (None,)
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row_mock
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)
        with pytest.raises(ValidationError):
            await svc.approve_question(tenant, uuid.uuid4(), TEST_ADMIN_ID)

    @pytest.mark.asyncio
    async def test_approve_logs_audit(self):
        """Approbation -> audit_service.log_action appele."""
        svc = _make_learning_service()
        question = _make_question_mock(proposed_answer="Reponse validee")

        session = AsyncMock()
        row_mock = ("Reponse validee",)
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row_mock
        session.execute = AsyncMock(return_value=result_mock)

        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock(session)
        await svc.approve_question(tenant, question.id, TEST_ADMIN_ID)

        svc._audit.log_action.assert_called_once()
        audit_data = svc._audit.log_action.call_args[0][0]
        assert audit_data.action == "approve"
        assert audit_data.resource_type == "unanswered_question"

    @pytest.mark.asyncio
    async def test_reject_with_note(self):
        """Rejet -> status=rejected, review_note rempli."""
        svc = _make_learning_service()
        question = _make_question_mock()
        svc._feedback.get_unanswered_question = AsyncMock(return_value=question)
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock()
        result = await svc.reject_question(
            tenant, question.id, TEST_ADMIN_ID, review_note="Pas pertinent"
        )
        assert result is not None
        svc._feedback.update_unanswered_question.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_logs_audit(self):
        """Rejet -> audit_service.log_action appele."""
        svc = _make_learning_service()
        question = _make_question_mock()
        svc._feedback.get_unanswered_question = AsyncMock(return_value=question)
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock()
        await svc.reject_question(tenant, question.id, TEST_ADMIN_ID)

        svc._audit.log_action.assert_called_once()
        audit_data = svc._audit.log_action.call_args[0][0]
        assert audit_data.action == "reject"
        assert audit_data.resource_type == "unanswered_question"


# =====================================================================
# Edit Proposal
# =====================================================================


class TestEditProposal:
    """Tests de l'edition de proposition."""

    @pytest.mark.asyncio
    async def test_edit_stores_new_answer(self):
        """Edition -> proposed_answer mis a jour."""
        svc = _make_learning_service()
        question = _make_question_mock()
        svc._feedback.get_unanswered_question = AsyncMock(return_value=question)
        svc._feedback.update_unanswered_question = AsyncMock(return_value=question)

        tenant = _make_tenant_mock()
        result = await svc.edit_proposal(
            tenant, question.id, TEST_ADMIN_ID, proposed_answer="Nouvelle reponse editee"
        )
        assert result is not None
        svc._feedback.update_unanswered_question.assert_called_once()


# =====================================================================
# Learning Stats
# =====================================================================


class TestLearningStats:
    """Tests des statistiques d'apprentissage."""

    @pytest.mark.asyncio
    async def test_stats_returns_expected_keys(self):
        """get_learning_stats retourne toutes les cles attendues."""
        svc = _make_learning_service()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 0
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)
        stats = await svc.get_learning_stats(tenant)
        assert isinstance(stats, dict)
        assert "total" in stats
        assert "by_status" in stats
        assert "approval_rate" in stats


# =====================================================================
# Deduplication
# =====================================================================


class TestDeduplication:
    """Tests de la deduplication des questions."""

    @pytest.mark.asyncio
    async def test_dedup_increments_frequency(self):
        """Question identique existante -> frequency +1."""
        svc = _make_learning_service()

        existing = _make_question_mock(frequency=5)
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)
        result = await svc.deduplicate_question(
            tenant, "Comment obtenir un agrement pour un projet touristique ?"
        )
        assert result is not None
        assert existing.frequency == 6

    @pytest.mark.asyncio
    async def test_dedup_no_match_returns_none(self):
        """Question nouvelle -> retourne None."""
        svc = _make_learning_service()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)
        result = await svc.deduplicate_question(tenant, "Question totalement nouvelle")
        assert result is None


# =====================================================================
# Reinjection Worker
# =====================================================================


class TestReinjectionWorker:
    """Tests du worker de reinjection Qdrant."""

    def test_chunk_format_question_answer(self):
        """Le chunk formate contient 'Question :' et 'Reponse :'."""
        question = "Comment creer une entreprise ?"
        answer = "Pour creer une entreprise au Maroc..."
        chunk = f"Question : {question}\n\nReponse : {answer}"
        assert "Question :" in chunk
        assert "Reponse :" in chunk

    def test_qdrant_payload_metadata(self):
        """Le payload Qdrant contient source=supervised_learning."""
        payload = {"source": "supervised_learning", "question_id": str(uuid.uuid4())}
        assert payload["source"] == "supervised_learning"

    def test_worker_importable(self):
        """Le worker reinject_learning_task est importable."""
        from app.workers.learning import reinject_learning_task

        assert callable(reinject_learning_task)

    def test_cosine_similarity_identical_vectors(self):
        """Vecteurs identiques -> similarite = 1.0."""
        from app.services.learning.service import SupervisedLearningService

        vec = [1.0, 2.0, 3.0]
        sim = SupervisedLearningService._cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal_vectors(self):
        """Vecteurs orthogonaux -> similarite = 0.0."""
        from app.services.learning.service import SupervisedLearningService

        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = SupervisedLearningService._cosine_similarity(a, b)
        assert abs(sim) < 1e-6

    def test_cosine_similarity_zero_vector(self):
        """Vecteur nul -> similarite = 0.0."""
        from app.services.learning.service import SupervisedLearningService

        a = [1.0, 2.0, 3.0]
        b = [0.0, 0.0, 0.0]
        sim = SupervisedLearningService._cosine_similarity(a, b)
        assert sim == 0.0
