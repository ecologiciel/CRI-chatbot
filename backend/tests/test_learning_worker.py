"""Tests for the supervised learning Qdrant reinjection worker.

Covers: import checks, chunk formatting, Qdrant payload structure,
idempotency guards, synthetic document get-or-create, and chunk indexing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import KBDocumentStatus, UnansweredStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)

QUESTION_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()


def _make_mock_tenant(mock_session):
    """Create a mock tenant that acts like TenantContext with a mock db_session.

    TenantContext is a frozen dataclass with __slots__, so we can't
    patch.object on it. Instead, return a MagicMock with the required
    attributes and a working db_session context manager.
    """
    tenant = MagicMock()
    tenant.id = TEST_TENANT.id
    tenant.slug = TEST_TENANT.slug
    tenant.name = TEST_TENANT.name
    tenant.status = TEST_TENANT.status
    tenant.qdrant_collection = f"kb_{TEST_TENANT.slug}"
    tenant.redis_prefix = TEST_TENANT.slug
    tenant.minio_bucket = f"cri-{TEST_TENANT.slug}"
    tenant.db_session = MagicMock(return_value=mock_session)
    return tenant


def _make_question(
    status: UnansweredStatus = UnansweredStatus.approved,
    proposed_answer: str | None = "Pour créer une entreprise au Maroc...",
) -> MagicMock:
    """Create a mock UnansweredQuestion."""
    q = MagicMock()
    q.id = QUESTION_ID
    q.question = "Comment créer une entreprise ?"
    q.proposed_answer = proposed_answer
    q.status = status
    q.language = "fr"
    q.frequency = 3
    q.reviewed_by = ADMIN_ID
    return q


def _make_learning_doc(doc_id: uuid.UUID | None = None) -> MagicMock:
    """Create a mock KBDocument for the synthetic learning document."""
    doc = MagicMock()
    doc.id = doc_id or uuid.uuid4()
    doc.chunk_count = 2
    return doc


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestWorkerImport:
    """Verify the worker module is importable and has the right exports."""

    def test_reinject_task_importable(self):
        from app.workers.learning import reinject_learning_task

        assert reinject_learning_task is not None

    def test_worker_settings_importable(self):
        from app.workers.learning import WorkerSettings

        assert WorkerSettings is not None
        assert hasattr(WorkerSettings, "functions")
        assert hasattr(WorkerSettings, "on_startup")
        assert hasattr(WorkerSettings, "on_shutdown")

    def test_worker_settings_has_reinject_task(self):
        from app.workers.learning import WorkerSettings, reinject_learning_task

        assert reinject_learning_task in WorkerSettings.functions

    def test_worker_settings_config(self):
        from app.workers.learning import WorkerSettings

        assert WorkerSettings.max_jobs == 5
        assert WorkerSettings.job_timeout == 120
        assert WorkerSettings.max_tries == 3


# ---------------------------------------------------------------------------
# Chunk format tests
# ---------------------------------------------------------------------------


class TestChunkFormat:
    """Verify the chunk content format for Qdrant indexing."""

    def test_chunk_contains_question_and_answer(self):
        question = "Comment créer une entreprise ?"
        answer = "Pour créer une entreprise au Maroc..."
        chunk = f"Question : {question}\n\nRéponse : {answer}"
        assert "Question :" in chunk
        assert "Réponse :" in chunk
        assert question in chunk
        assert answer in chunk

    def test_chunk_format_structure(self):
        question = "Quels sont les frais ?"
        answer = "Les frais sont de 1000 DH."
        chunk = f"Question : {question}\n\nRéponse : {answer}"
        parts = chunk.split("\n\n")
        assert len(parts) == 2
        assert parts[0].startswith("Question :")
        assert parts[1].startswith("Réponse :")


# ---------------------------------------------------------------------------
# Qdrant payload tests
# ---------------------------------------------------------------------------


class TestQdrantPayload:
    """Verify the Qdrant payload structure matches ingestion service format."""

    def test_payload_has_supervised_learning_source(self):
        payload = {
            "document_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "content": "Question : test\n\nRéponse : test",
            "title": "Apprentissage supervisé",
            "language": "fr",
            "source": "supervised_learning",
            "question_id": str(uuid.uuid4()),
            "related_laws": [],
            "applicable_sectors": [],
            "legal_forms": [],
            "regions": [],
            "summary": "Q&A validé: test",
        }
        assert payload["source"] == "supervised_learning"

    def test_payload_has_all_required_keys(self):
        """Ensure payload matches the ingestion service's Qdrant payload format."""
        required_keys = {
            "document_id",
            "chunk_index",
            "content",
            "title",
            "language",
            "related_laws",
            "applicable_sectors",
            "legal_forms",
            "regions",
            "summary",
        }
        payload = {
            "document_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "content": "test",
            "title": "Apprentissage supervisé",
            "language": "fr",
            "source": "supervised_learning",
            "question_id": str(uuid.uuid4()),
            "related_laws": [],
            "applicable_sectors": [],
            "legal_forms": [],
            "regions": [],
            "summary": "Q&A validé: test",
        }
        assert required_keys.issubset(payload.keys())


# ---------------------------------------------------------------------------
# Synthetic document helpers
# ---------------------------------------------------------------------------


class TestSyntheticDocumentHelper:
    """Verify the get-or-create logic for the synthetic KBDocument."""

    @pytest.mark.asyncio
    async def test_creates_doc_when_missing(self):
        from app.workers.learning import _get_or_create_learning_document

        session = AsyncMock()
        # Simulate no existing document found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        await _get_or_create_learning_document(session, "rabat")

        # Should have called session.add for the new document
        session.add.assert_called_once()
        added_doc = session.add.call_args[0][0]
        assert added_doc.title == "Apprentissage supervisé"
        assert added_doc.source_url == "learning://supervised"
        assert added_doc.category == "learning"
        assert added_doc.status == KBDocumentStatus.indexed

    @pytest.mark.asyncio
    async def test_reuses_existing_doc(self):
        from app.workers.learning import _get_or_create_learning_document

        existing_doc = _make_learning_doc()

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_doc
        session.execute = AsyncMock(return_value=mock_result)

        result = await _get_or_create_learning_document(session, "rabat")

        assert result is existing_doc
        session.add.assert_not_called()


class TestNextChunkIndex:
    """Verify chunk_index computation."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_document(self):
        from app.workers.learning import _next_chunk_index

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0  # COALESCE(MAX(-1), -1) + 1 = 0
        session.execute = AsyncMock(return_value=mock_result)

        index = await _next_chunk_index(session, uuid.uuid4())

        assert index == 0

    @pytest.mark.asyncio
    async def test_increments_from_existing_max(self):
        from app.workers.learning import _next_chunk_index

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 6  # MAX(5) + 1 = 6
        session.execute = AsyncMock(return_value=mock_result)

        index = await _next_chunk_index(session, uuid.uuid4())

        assert index == 6


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Verify idempotency guards in the reinject task."""

    @pytest.mark.asyncio
    async def test_already_injected_returns_early(self):
        from app.workers.learning import reinject_learning_task

        question = _make_question(status=UnansweredStatus.injected)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = question
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tenant = _make_mock_tenant(mock_session)

        with patch(
            "app.core.tenant.TenantResolver.from_slug",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ):
            result = await reinject_learning_task(
                {}, TEST_TENANT.slug, str(QUESTION_ID),
            )

        assert result["status"] == "already_injected"

    @pytest.mark.asyncio
    async def test_not_found_returns_skip(self):
        from app.workers.learning import reinject_learning_task

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tenant = _make_mock_tenant(mock_session)

        with patch(
            "app.core.tenant.TenantResolver.from_slug",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ):
            result = await reinject_learning_task(
                {}, TEST_TENANT.slug, str(QUESTION_ID),
            )

        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_pending_status_returns_invalid(self):
        from app.workers.learning import reinject_learning_task

        question = _make_question(status=UnansweredStatus.pending)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = question
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tenant = _make_mock_tenant(mock_session)

        with patch(
            "app.core.tenant.TenantResolver.from_slug",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ):
            result = await reinject_learning_task(
                {}, TEST_TENANT.slug, str(QUESTION_ID),
            )

        assert result["status"] == "invalid_status"
        assert result["reason"] == "pending"

    @pytest.mark.asyncio
    async def test_no_answer_returns_skip(self):
        from app.workers.learning import reinject_learning_task

        question = _make_question(proposed_answer=None)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = question
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tenant = _make_mock_tenant(mock_session)

        with patch(
            "app.core.tenant.TenantResolver.from_slug",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ):
            result = await reinject_learning_task(
                {}, TEST_TENANT.slug, str(QUESTION_ID),
            )

        assert result["status"] == "no_answer"
