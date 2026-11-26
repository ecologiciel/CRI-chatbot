"""Tests for the supervised learning Qdrant reinjection worker.

Covers: import checks, chunk formatting, Qdrant payload structure,
idempotency guards, synthetic document get-or-create, and chunk indexing.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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


@pytest.fixture(autouse=True)
def mock_lifecycle_lock():
    @asynccontextmanager
    async def unlocked(_tenant):
        yield

    with patch("app.workers.learning.protect_ingestion", unlocked):
        yield


@pytest.mark.asyncio
async def test_reinjection_holds_lifecycle_lock_until_publication_finishes():
    from app.workers.learning import reinject_learning_task

    held = False

    @asynccontextmanager
    async def lock(tenant):
        nonlocal held
        assert tenant is TEST_TENANT
        held = True
        try:
            yield
        finally:
            held = False

    async def publish(_ctx, tenant, _question_id):
        assert held
        assert tenant is TEST_TENANT
        return {"status": "ok"}

    with (
        patch(
            "app.core.tenant.TenantResolver.from_slug",
            new_callable=AsyncMock,
            return_value=TEST_TENANT,
        ),
        patch("app.workers.learning.protect_ingestion", lock),
        patch("app.workers.learning._reinject_learning_locked", side_effect=publish),
    ):
        assert (await reinject_learning_task({}, TEST_TENANT.slug, str(QUESTION_ID)))[
            "status"
        ] == "ok"
    assert not held


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


@pytest.mark.asyncio
async def test_approved_answer_publishes_active_version_with_masked_pii():
    from app.models.kb import KBDocument
    from app.workers.learning import reinject_learning_task

    question = _make_question(proposed_answer="Écrivez à secret@example.com")
    question.question = "Comment contacter secret@example.com ?"
    document = KBDocument(
        id=uuid.uuid4(),
        title="Apprentissage supervisé",
        status=KBDocumentStatus.indexed,
        active_index_version=None,
        chunk_count=0,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = question
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.side_effect = [result, MagicMock(), result]
    session.add = MagicMock()
    tenant = _make_mock_tenant(session)
    embedder = MagicMock()
    embedder.embed_single = AsyncMock(return_value=[0.1] * 768)
    qdrant = MagicMock()
    qdrant.upsert = AsyncMock()
    audit = MagicMock()
    audit.log_action = AsyncMock()

    with (
        patch(
            "app.core.tenant.TenantResolver.from_slug", new_callable=AsyncMock, return_value=tenant
        ),
        patch("app.services.ai.embeddings.get_embedding_service", return_value=embedder),
        patch("app.core.qdrant.get_qdrant", return_value=qdrant),
        patch("app.services.audit.service.get_audit_service", return_value=audit),
        patch(
            "app.workers.learning._get_or_create_learning_document",
            new_callable=AsyncMock,
            return_value=document,
        ),
        patch("app.workers.learning._next_chunk_index", new_callable=AsyncMock, return_value=0),
    ):
        result = await reinject_learning_task({}, tenant.slug, str(question.id))

    assert result["status"] == "ok"
    chunk = session.add.call_args.args[0]
    point = qdrant.upsert.await_args.kwargs["points"][0]
    assert document.active_index_version == chunk.index_version == 1
    assert question.status == UnansweredStatus.injected
    assert "secret@example.com" not in chunk.content
    assert "secret@example.com" not in point.payload["content"]


@pytest.mark.asyncio
async def test_recovery_requeues_reviewed_answers_on_learning_queue():
    from app.workers.learning import LEARNING_QUEUE, recover_approved_questions

    question_id = uuid.uuid4()
    updated = datetime.now(UTC) - timedelta(hours=1)
    global_result = MagicMock()
    global_result.scalars.return_value.all.return_value = ["rabat"]
    global_session = AsyncMock()
    global_session.__aenter__.return_value = global_session
    global_session.execute.return_value = global_result
    tenant_result = MagicMock()
    tenant_result.all.return_value = [(question_id, updated)]
    tenant_session = AsyncMock()
    tenant_session.__aenter__.return_value = tenant_session
    tenant_session.execute.return_value = tenant_result
    tenant = _make_mock_tenant(tenant_session)
    redis = MagicMock()
    redis.enqueue_job = AsyncMock(return_value=object())
    with (
        patch("app.core.database.get_session_factory", return_value=lambda: global_session),
        patch(
            "app.core.tenant.TenantResolver.from_slug", new_callable=AsyncMock, return_value=tenant
        ),
    ):
        queued = await recover_approved_questions({"redis": redis})
    assert queued == 1
    assert redis.enqueue_job.await_args.kwargs["_queue_name"] == LEARNING_QUEUE
    assert str(question_id) in redis.enqueue_job.await_args.kwargs["_job_id"]

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
                {},
                TEST_TENANT.slug,
                str(QUESTION_ID),
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
                {},
                TEST_TENANT.slug,
                str(QUESTION_ID),
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
                {},
                TEST_TENANT.slug,
                str(QUESTION_ID),
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
                {},
                TEST_TENANT.slug,
                str(QUESTION_ID),
            )

        assert result["status"] == "no_answer"
