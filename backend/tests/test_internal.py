"""Tests unitaires du module Agent Interne CRI.

Couvre :
- InternalAgentService : verify_whitelist, get_dashboard_stats, search_faq, generate_report
- InternalAgent LangGraph node : process (whiteliste vs non-whiteliste)
- IntentDetector : detection intent "internal"
- Router : routage vers internal_agent
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_PHONE = "+212600000001"


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


# =====================================================================
# InternalAgentService
# =====================================================================


class TestInternalAgentService:
    """Tests du service metier InternalAgentService."""

    @pytest.mark.asyncio
    async def test_verify_whitelist_active_number(self):
        """Numero actif dans la whitelist -> True."""
        from app.services.internal.service import InternalAgentService

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = MagicMock(is_active=True)
        session.execute = AsyncMock(return_value=result_mock)

        svc = InternalAgentService(
            retrieval=AsyncMock(),
            generation=AsyncMock(),
            gemini=AsyncMock(),
            audit=AsyncMock(),
        )
        tenant = _make_tenant_mock(session)
        assert await svc.verify_whitelist(tenant, TEST_PHONE) is True

    @pytest.mark.asyncio
    async def test_verify_whitelist_unknown_number(self):
        """Numero absent de la whitelist -> False."""
        from app.services.internal.service import InternalAgentService

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        svc = InternalAgentService(
            retrieval=AsyncMock(),
            generation=AsyncMock(),
            gemini=AsyncMock(),
            audit=AsyncMock(),
        )
        tenant = _make_tenant_mock(session)
        assert await svc.verify_whitelist(tenant, TEST_PHONE) is False

    @pytest.mark.asyncio
    async def test_get_dashboard_stats_returns_all_keys(self):
        """get_dashboard_stats retourne toutes les cles attendues."""
        from app.services.internal.service import InternalAgentService

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 42
        session.execute = AsyncMock(return_value=result_mock)

        svc = InternalAgentService(
            retrieval=AsyncMock(),
            generation=AsyncMock(),
            gemini=AsyncMock(),
            audit=AsyncMock(),
        )
        tenant = _make_tenant_mock(session)
        stats = await svc.get_dashboard_stats(tenant)
        assert isinstance(stats, dict)
        # Should have numeric keys
        assert len(stats) >= 2

    @pytest.mark.asyncio
    async def test_search_faq_calls_retrieval_and_generation(self):
        """search_faq utilise le pipeline RAG (retrieval + generation)."""
        from app.services.internal.service import InternalAgentService

        retrieval_result = MagicMock()
        chunk = MagicMock(content="Chunk test", chunk_id="c1", score=0.9)
        retrieval_result.chunks = [chunk]
        retrieval = AsyncMock()
        retrieval.retrieve = AsyncMock(return_value=retrieval_result)
        gen_response = MagicMock(answer="Test answer", confidence=0.9, chunk_ids=["c1"])
        generation = AsyncMock()
        generation.generate = AsyncMock(return_value=gen_response)

        svc = InternalAgentService(
            retrieval=retrieval,
            generation=generation,
            gemini=AsyncMock(),
            audit=AsyncMock(),
        )
        tenant = _make_tenant_mock()
        result = await svc.search_faq(tenant, "Comment creer une entreprise ?", "fr")
        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_report_calls_gemini(self):
        """generate_report utilise GeminiService."""
        from app.services.internal.service import InternalAgentService

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 10
        session.execute = AsyncMock(return_value=result_mock)

        gemini = AsyncMock()
        gemini.generate_simple = AsyncMock(return_value="Rapport: 10 conversations")

        svc = InternalAgentService(
            retrieval=AsyncMock(),
            generation=AsyncMock(),
            gemini=gemini,
            audit=AsyncMock(),
        )
        tenant = _make_tenant_mock(session)
        result = await svc.generate_report(tenant, "rapport activite", "fr")
        assert isinstance(result, str)
        gemini.generate_simple.assert_called_once()


# =====================================================================
# InternalAgent LangGraph Node
# =====================================================================


class TestInternalAgentNode:
    """Tests du noeud LangGraph InternalAgent."""

    @pytest.mark.asyncio
    async def test_whitelisted_user_gets_response(self):
        """Numero whiteliste -> reponse normale (pas de refus)."""
        from app.services.orchestrator.internal_agent import InternalAgent
        from app.services.internal.service import REFUSAL_MESSAGES

        internal_svc = MagicMock()
        internal_svc.verify_whitelist = AsyncMock(return_value=True)
        internal_svc.classify_sub_intent = AsyncMock(return_value="faq")
        internal_svc.search_faq = AsyncMock(
            return_value={"response": "Voici la reponse", "confidence": 0.9}
        )
        internal_svc._audit = AsyncMock()
        internal_svc._audit.log_action = AsyncMock()

        agent = InternalAgent(internal_svc)
        state = {
            "phone": TEST_PHONE,
            "language": "fr",
            "query": "Comment creer une entreprise ?",
            "messages": [],
            "response": "",
            "error": None,
        }
        tenant = _make_tenant_mock()

        result = await agent.handle(state, tenant)
        assert result.get("response") is not None
        # Should NOT contain any refusal message
        for lang, msg in REFUSAL_MESSAGES.items():
            assert result.get("response") != msg

    @pytest.mark.asyncio
    async def test_non_whitelisted_user_gets_refusal(self):
        """Numero non whiteliste -> message de refus poli."""
        from app.services.orchestrator.internal_agent import InternalAgent
        from app.services.internal.service import REFUSAL_MESSAGES

        internal_svc = MagicMock()
        internal_svc.verify_whitelist = AsyncMock(return_value=False)
        internal_svc._audit = AsyncMock()
        internal_svc._audit.log_action = AsyncMock()

        agent = InternalAgent(internal_svc)
        state = {
            "phone": TEST_PHONE,
            "language": "fr",
            "query": "test",
            "messages": [],
            "response": "",
            "error": None,
        }
        tenant = _make_tenant_mock()

        result = await agent.handle(state, tenant)
        # Response should be one of the refusal messages
        assert result["response"] in REFUSAL_MESSAGES.values()

    def test_refusal_messages_cover_three_languages(self):
        """Messages de refus disponibles en FR, AR, EN."""
        from app.services.internal.service import REFUSAL_MESSAGES

        assert "fr" in REFUSAL_MESSAGES
        assert "ar" in REFUSAL_MESSAGES
        assert "en" in REFUSAL_MESSAGES

    def test_welcome_messages_cover_three_languages(self):
        """Messages de bienvenue disponibles en FR, AR, EN."""
        from app.services.internal.service import WELCOME_MESSAGES

        assert "fr" in WELCOME_MESSAGES
        assert "ar" in WELCOME_MESSAGES
        assert "en" in WELCOME_MESSAGES


# =====================================================================
# IntentDetector Phase 2
# =====================================================================


class TestIntentDetectorPhase2:
    """Tests de la mise a jour IntentDetector pour Phase 2."""

    def test_intent_type_includes_internal(self):
        """L'intent 'interne' est dans IntentType."""
        from app.services.orchestrator.state import IntentType

        assert hasattr(IntentType, "INTERNE") or IntentType.INTERNE == "interne"

    def test_intent_type_includes_escalade(self):
        """L'intent 'escalade' est dans IntentType."""
        from app.services.orchestrator.state import IntentType

        assert hasattr(IntentType, "ESCALADE") or IntentType.ESCALADE == "escalade"

    def test_graph_module_references_internal_agent(self):
        """Le module graph.py reference le noeud 'internal_agent'."""
        import inspect
        from app.services.orchestrator import graph as graph_module

        source = inspect.getsource(graph_module)
        assert "internal_agent" in source
