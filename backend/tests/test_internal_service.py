"""Tests for InternalAgentService and InternalAgent LangGraph node."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.schemas.audit import AuditLogCreate
from app.schemas.rag import GenerationResponse
from app.services.internal.service import (
    REFUSAL_MESSAGES,
    WELCOME_MESSAGES,
    InternalAgentService,
)
from app.services.orchestrator.internal_agent import _STATS_TEMPLATES, InternalAgent
from app.services.orchestrator.state import ConversationState, IntentType
from app.services.rag.prompts import PromptTemplates

# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_state(**overrides) -> ConversationState:
    """Create a minimal ConversationState for testing."""
    state: ConversationState = {
        "tenant_slug": "rabat",
        "phone": "+212600000000",
        "language": "fr",
        "intent": "interne",
        "query": "Quelles sont les statistiques du jour ?",
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
        "is_internal_user": False,
        "agent_type": "public",
        "escalation_id": None,
        "consecutive_low_confidence": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _make_service(
    mock_retrieval=None,
    mock_generation=None,
    mock_gemini=None,
    mock_audit=None,
):
    """Create InternalAgentService with mocked dependencies."""
    retrieval = mock_retrieval or AsyncMock()
    generation = mock_generation or AsyncMock()
    gemini = mock_gemini or AsyncMock()
    audit = mock_audit or AsyncMock()
    service = InternalAgentService(
        retrieval=retrieval,
        generation=generation,
        gemini=gemini,
        audit=audit,
    )
    return service, retrieval, generation, gemini, audit


def _make_chunk(chunk_id="chunk_1", score=0.85, content="Info about SARL"):
    """Create a mock RetrievedChunk."""
    chunk = MagicMock()
    chunk.chunk_id = chunk_id
    chunk.content = content
    chunk.score = score
    chunk.metadata = {}
    return chunk


def _make_retrieval_result(chunks=None, confidence=0.85):
    """Create a mock RetrievalResult."""
    if chunks is None:
        chunks = [_make_chunk("c1", 0.9), _make_chunk("c2", 0.8)]
    return MagicMock(
        chunks=chunks,
        confidence=confidence,
    )


def _make_generation_response(
    answer="Pour créer une SARL...",
    chunk_ids=None,
    confidence=0.85,
):
    """Create a GenerationResponse."""
    return GenerationResponse(
        answer=answer,
        language="fr",
        chunk_ids=chunk_ids or ["c1", "c2"],
        confidence=confidence,
        is_confident=confidence >= 0.7,
        disclaimer=None,
        model="gemini-2.5-flash",
        input_tokens=200,
        output_tokens=150,
        total_tokens=350,
        latency_ms=850.0,
    )


# ==========================================================================
# InternalAgentService tests
# ==========================================================================


class TestInternalAgentService:
    """Tests for InternalAgentService business logic."""

    # -- verify_whitelist --

    @pytest.mark.asyncio
    async def test_verify_whitelist_found(self):
        """Whitelisted and active phone returns True."""
        service, *_ = _make_service()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(TenantContext, "db_session", return_value=mock_ctx):
            result = await service.verify_whitelist(TEST_TENANT, "+212600000000")

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_whitelist_not_found(self):
        """Non-whitelisted phone returns False."""
        service, *_ = _make_service()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(TenantContext, "db_session", return_value=mock_ctx):
            result = await service.verify_whitelist(TEST_TENANT, "+212699999999")

        assert result is False

    @pytest.mark.asyncio
    async def test_verify_whitelist_db_error(self):
        """DB error returns False (fail-closed)."""
        service, *_ = _make_service()

        with patch.object(
            TenantContext,
            "db_session",
            side_effect=RuntimeError("DB down"),
        ):
            result = await service.verify_whitelist(TEST_TENANT, "+212600000000")

        assert result is False

    # -- classify_sub_intent --

    @pytest.mark.asyncio
    async def test_classify_sub_intent_stats(self):
        """Gemini returns 'stats' → returns 'stats'."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="stats")
        service, *_ = _make_service(mock_gemini=mock_gemini)

        result = await service.classify_sub_intent("combien de conversations", TEST_TENANT)

        assert result == "stats"

    @pytest.mark.asyncio
    async def test_classify_sub_intent_faq(self):
        """Gemini returns 'faq' → returns 'faq'."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="faq")
        service, *_ = _make_service(mock_gemini=mock_gemini)

        result = await service.classify_sub_intent("comment créer une SARL", TEST_TENANT)

        assert result == "faq"

    @pytest.mark.asyncio
    async def test_classify_sub_intent_report(self):
        """Gemini returns 'report' → returns 'report'."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="report")
        service, *_ = _make_service(mock_gemini=mock_gemini)

        result = await service.classify_sub_intent("fais-moi un bilan", TEST_TENANT)

        assert result == "report"

    @pytest.mark.asyncio
    async def test_classify_sub_intent_unknown_defaults_faq(self):
        """Unrecognized Gemini output → defaults to 'faq'."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="something_else")
        service, *_ = _make_service(mock_gemini=mock_gemini)

        result = await service.classify_sub_intent("test", TEST_TENANT)

        assert result == "faq"

    @pytest.mark.asyncio
    async def test_classify_sub_intent_error_defaults_faq(self):
        """Gemini error → defaults to 'faq'."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(
            side_effect=RuntimeError("API error"),
        )
        service, *_ = _make_service(mock_gemini=mock_gemini)

        result = await service.classify_sub_intent("test", TEST_TENANT)

        assert result == "faq"

    # -- get_dashboard_stats --

    @pytest.mark.asyncio
    async def test_get_dashboard_stats(self):
        """Returns correct stat counts from DB."""
        service, *_ = _make_service()

        # Mock 3 sequential execute() calls returning scalar values
        mock_session = AsyncMock()
        conv_result = MagicMock()
        conv_result.scalar_one.return_value = 42
        unanswered_result = MagicMock()
        unanswered_result.scalar_one.return_value = 5
        contact_result = MagicMock()
        contact_result.scalar_one.return_value = 120

        mock_session.execute = AsyncMock(
            side_effect=[conv_result, unanswered_result, contact_result],
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(TenantContext, "db_session", return_value=mock_ctx):
            stats = await service.get_dashboard_stats(TEST_TENANT)

        assert stats["total_conversations"] == 42
        assert stats["pending_unanswered"] == 5
        assert stats["total_contacts"] == 120

    # -- search_faq --

    @pytest.mark.asyncio
    async def test_search_faq_success(self):
        """RAG retrieval + generation returns response with chunks."""
        retrieval_result = _make_retrieval_result()
        gen_response = _make_generation_response()

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        mock_generation = AsyncMock()
        mock_generation.generate = AsyncMock(return_value=gen_response)

        service, *_ = _make_service(
            mock_retrieval=mock_retrieval,
            mock_generation=mock_generation,
        )

        result = await service.search_faq(
            TEST_TENANT,
            "Comment créer une SARL ?",
            "fr",
        )

        assert result["response"] == "Pour créer une SARL..."
        assert result["confidence"] == 0.85
        assert result["chunk_ids"] == ["c1", "c2"]
        assert len(result["retrieved_chunks"]) == 2

    @pytest.mark.asyncio
    async def test_search_faq_no_chunks(self):
        """No chunks retrieved → returns 'no_answer'."""
        retrieval_result = _make_retrieval_result(chunks=[])

        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(return_value=retrieval_result)

        service, *_ = _make_service(mock_retrieval=mock_retrieval)

        result = await service.search_faq(TEST_TENANT, "question", "fr")

        expected = PromptTemplates.get_message("no_answer", "fr")
        assert result["response"] == expected
        assert result["confidence"] == 0.0
        assert result["chunk_ids"] == []

    # -- generate_report --

    @pytest.mark.asyncio
    async def test_generate_report(self):
        """Generates report from stats via Gemini."""
        mock_gemini = AsyncMock()
        mock_gemini.generate_simple = AsyncMock(return_value="Rapport: 42 conversations")
        service, *_ = _make_service(mock_gemini=mock_gemini)

        # Mock get_dashboard_stats
        with patch.object(
            service,
            "get_dashboard_stats",
            return_value={
                "total_conversations": 42,
                "pending_unanswered": 5,
                "total_contacts": 120,
            },
        ):
            result = await service.generate_report(
                TEST_TENANT,
                "fais un rapport",
                "fr",
            )

        assert result == "Rapport: 42 conversations"
        mock_gemini.generate_simple.assert_awaited_once()


# ==========================================================================
# InternalAgent (LangGraph node) tests
# ==========================================================================


class TestInternalAgent:
    """Tests for the InternalAgent LangGraph node."""

    def _make_agent(self, mock_service=None):
        """Create InternalAgent with mocked service."""
        service = mock_service or AsyncMock(spec=InternalAgentService)
        service._audit = AsyncMock()
        service._audit.log_action = AsyncMock()
        return InternalAgent(internal_service=service), service

    @pytest.mark.asyncio
    async def test_handle_whitelisted_faq(self):
        """Whitelisted user, FAQ sub-intent → RAG response."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=True)
        service.classify_sub_intent = AsyncMock(return_value="faq")
        service.search_faq = AsyncMock(
            return_value={
                "response": "Voici la réponse.",
                "confidence": 0.85,
                "chunk_ids": ["c1"],
                "retrieved_chunks": [{"chunk_id": "c1", "content": "...", "score": 0.9}],
            }
        )

        state = _make_state(query="Comment créer une SARL ?")
        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == "Voici la réponse."
        assert result["is_internal_user"] is True
        assert result["agent_type"] == "internal"
        assert result["chunk_ids"] == ["c1"]
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_handle_whitelisted_stats(self):
        """Whitelisted user, stats sub-intent → formatted stats."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=True)
        service.classify_sub_intent = AsyncMock(return_value="stats")
        service.get_dashboard_stats = AsyncMock(
            return_value={
                "total_conversations": 42,
                "pending_unanswered": 5,
                "total_contacts": 120,
            }
        )

        state = _make_state(query="statistiques du jour")
        result = await agent.handle(state, TEST_TENANT)

        assert "42" in result["response"]
        assert "5" in result["response"]
        assert "120" in result["response"]
        assert result["is_internal_user"] is True
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_handle_whitelisted_report(self):
        """Whitelisted user, report sub-intent → Gemini report."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=True)
        service.classify_sub_intent = AsyncMock(return_value="report")
        service.generate_report = AsyncMock(return_value="Rapport hebdomadaire...")

        state = _make_state(query="fais-moi un bilan")
        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == "Rapport hebdomadaire..."
        assert result["is_internal_user"] is True
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_handle_not_whitelisted(self):
        """Non-whitelisted user → refusal message."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=False)

        state = _make_state(query="donne-moi les stats")
        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == REFUSAL_MESSAGES["fr"]
        assert result["is_internal_user"] is False

    @pytest.mark.asyncio
    async def test_handle_not_whitelisted_arabic(self):
        """Non-whitelisted user with Arabic → Arabic refusal."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=False)

        state = _make_state(language="ar", query="أعطني الإحصائيات")
        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == REFUSAL_MESSAGES["ar"]
        assert result["is_internal_user"] is False

    @pytest.mark.asyncio
    async def test_handle_not_whitelisted_english(self):
        """Non-whitelisted user with English → English refusal."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=False)

        state = _make_state(language="en", query="give me stats")
        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == REFUSAL_MESSAGES["en"]

    @pytest.mark.asyncio
    async def test_handle_audit_logged_on_access(self):
        """Audit log is written on whitelisted access."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=True)
        service.classify_sub_intent = AsyncMock(return_value="stats")
        service.get_dashboard_stats = AsyncMock(
            return_value={
                "total_conversations": 0,
                "pending_unanswered": 0,
                "total_contacts": 0,
            }
        )

        state = _make_state()
        await agent.handle(state, TEST_TENANT)

        service._audit.log_action.assert_awaited_once()
        audit_data = service._audit.log_action.call_args[0][0]
        assert isinstance(audit_data, AuditLogCreate)
        assert audit_data.tenant_slug == "rabat"
        assert audit_data.user_type == "internal"
        assert audit_data.action == "access"
        assert audit_data.resource_type == "internal_agent"
        assert audit_data.details["is_whitelisted"] is True

    @pytest.mark.asyncio
    async def test_handle_audit_logged_on_refusal(self):
        """Audit log is written even when access is denied."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(return_value=False)

        state = _make_state()
        await agent.handle(state, TEST_TENANT)

        service._audit.log_action.assert_awaited_once()
        audit_data = service._audit.log_action.call_args[0][0]
        assert audit_data.details["is_whitelisted"] is False

    @pytest.mark.asyncio
    async def test_handle_error_handling(self):
        """Service error → graceful fallback with 'no_answer'."""
        agent, service = self._make_agent()
        service.verify_whitelist = AsyncMock(
            side_effect=RuntimeError("unexpected error"),
        )

        state = _make_state()
        result = await agent.handle(state, TEST_TENANT)

        expected = PromptTemplates.get_message("no_answer", "fr")
        assert result["response"] == expected
        assert result["error"] == "unexpected error"
        assert result["confidence"] == 0.0


# ==========================================================================
# Module-level imports and constants tests
# ==========================================================================


class TestImportsAndConstants:
    """Verify module imports and structural contracts."""

    def test_internal_service_import(self):
        """InternalAgentService is importable."""
        from app.services.internal.service import InternalAgentService

        assert InternalAgentService is not None

    def test_internal_agent_node_import(self):
        """InternalAgent LangGraph node is importable."""
        from app.services.orchestrator.internal_agent import InternalAgent

        assert InternalAgent is not None

    def test_refusal_messages_trilingual(self):
        """Refusal messages cover FR/AR/EN."""
        assert "fr" in REFUSAL_MESSAGES
        assert "ar" in REFUSAL_MESSAGES
        assert "en" in REFUSAL_MESSAGES

    def test_welcome_messages_trilingual(self):
        """Welcome messages cover FR/AR/EN."""
        assert "fr" in WELCOME_MESSAGES
        assert "ar" in WELCOME_MESSAGES
        assert "en" in WELCOME_MESSAGES

    def test_stats_templates_trilingual(self):
        """Stats formatting templates cover FR/AR/EN."""
        assert "fr" in _STATS_TEMPLATES
        assert "ar" in _STATS_TEMPLATES
        assert "en" in _STATS_TEMPLATES

    def test_conversation_state_phase2_fields(self):
        """ConversationState includes Phase 2 fields."""
        annotations = ConversationState.__annotations__
        assert "is_internal_user" in annotations
        assert "agent_type" in annotations
        assert "escalation_id" in annotations
        assert "consecutive_low_confidence" in annotations

    def test_intent_type_includes_interne(self):
        """IntentType has INTERNE and ESCALADE constants."""
        assert IntentType.INTERNE == "interne"
        assert IntentType.ESCALADE == "escalade"
        assert "interne" in IntentType.ALL
        assert "escalade" in IntentType.ALL

    def test_router_routes_internal(self):
        """Router maps intent 'interne' to 'internal_agent'."""
        from app.services.orchestrator.router import Router

        state = _make_state(intent="interne")
        assert Router.route(state) == "internal_agent"
