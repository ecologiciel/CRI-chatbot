"""Tests unitaires du module Escalade Agent Humain.

Couvre :
- EscalationService : detect_escalation (6 scenarios), create, assign, respond, close
- EscalationHandler LangGraph node : process
- Trigger-priority mapping
- Trilingual messages
"""

from __future__ import annotations

import json
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

from app.models.enums import (
    EscalationPriority,
    EscalationStatus,
    EscalationTrigger,
)

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_ADMIN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TEST_CONVERSATION_ID = uuid.uuid4()
TEST_ESCALATION_ID = uuid.uuid4()


def _make_tenant_mock(session_mock=None):
    """Create a MagicMock tenant with db_session async context manager."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = "rabat"
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.redis_prefix = "rabat"
    tenant.whatsapp_config = {
        "phone_number_id": "111222333",
        "access_token": "test_token",
    }

    if session_mock:

        @asynccontextmanager
        async def fake_db():
            yield session_mock

        tenant.db_session = fake_db
    return tenant


def _make_escalation_service():
    """Create an EscalationService with all dependencies mocked."""
    from app.services.escalation.service import EscalationService

    return EscalationService(
        gemini=AsyncMock(),
        sender=AsyncMock(),
        audit=AsyncMock(),
    )


# =====================================================================
# Detection
# =====================================================================


class TestEscalationDetection:
    """Tests des 6 scenarios de detection d'escalade."""

    @pytest.mark.asyncio
    async def test_detect_explicit_request(self):
        """Intent 'escalade' -> EscalationTrigger.explicit_request."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation({"intent": "escalade"})
        assert result == EscalationTrigger.explicit_request

    @pytest.mark.asyncio
    async def test_detect_rag_failure_two_consecutive(self):
        """2 echecs RAG consecutifs (confidence < 0.5) -> rag_failure."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation({"consecutive_low_confidence": 2})
        assert result == EscalationTrigger.rag_failure

    @pytest.mark.asyncio
    async def test_detect_rag_failure_single_not_triggered(self):
        """1 seul echec RAG -> pas d'escalade."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation({"consecutive_low_confidence": 1})
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_sensitive_topic(self):
        """Guard message contenant 'sensitive' -> sensitive_topic."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation(
            {"guard_message": "Detected sensitive topic"}
        )
        assert result == EscalationTrigger.sensitive_topic

    @pytest.mark.asyncio
    async def test_detect_negative_feedback_with_agent_keyword(self):
        """Mot-cle 'parler' + low confidence -> negative_feedback."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation(
            {"query": "Je veux parler a un agent", "confidence": 0.3}
        )
        assert result == EscalationTrigger.negative_feedback

    @pytest.mark.asyncio
    async def test_detect_no_escalation_normal_flow(self):
        """Flux normal (bon score, pas de demande) -> None."""
        svc = _make_escalation_service()
        result = await svc.detect_escalation(
            {
                "intent": "faq",
                "confidence": 0.9,
                "query": "Quels sont les documents necessaires ?",
                "consecutive_low_confidence": 0,
            }
        )
        assert result is None


# =====================================================================
# Trigger Priority Mapping
# =====================================================================


class TestTriggerPriorityMapping:
    """Tests du mapping trigger -> priorite."""

    def test_all_triggers_have_priority(self):
        """Chaque trigger a une priorite par defaut definie."""
        from app.services.escalation.service import EscalationService

        for trigger in EscalationTrigger:
            assert trigger in EscalationService.TRIGGER_PRIORITY_MAP, (
                f"Missing priority for {trigger}"
            )

    def test_explicit_request_is_high(self):
        """explicit_request -> high priority."""
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.explicit_request]
            == EscalationPriority.high
        )

    def test_rag_failure_is_medium(self):
        """rag_failure -> medium priority."""
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.rag_failure]
            == EscalationPriority.medium
        )

    def test_otp_timeout_is_low(self):
        """otp_timeout -> low priority."""
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.otp_timeout]
            == EscalationPriority.low
        )


# =====================================================================
# Lifecycle — Create
# =====================================================================


class TestEscalationLifecycle:
    """Tests du cycle de vie d'une escalade."""

    @pytest.mark.asyncio
    async def test_create_escalation_sets_pending_status(self):
        """Nouvelle escalade -> status=pending."""
        svc = _make_escalation_service()
        svc._gemini.generate_simple = AsyncMock(return_value="Resume de la conversation")

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        session.add = MagicMock()
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            mock_redis.return_value.publish = AsyncMock()
            escalation = await svc.create_escalation(
                TEST_CONVERSATION_ID,
                EscalationTrigger.explicit_request,
                "Je veux parler a un agent",
                tenant,
            )

        assert escalation.status == EscalationStatus.pending

    @pytest.mark.asyncio
    async def test_create_escalation_publishes_redis(self):
        """Creation d'escalade -> message publie sur Redis pub/sub."""
        svc = _make_escalation_service()
        svc._gemini.generate_simple = AsyncMock(return_value="Resume")

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        session.add = MagicMock()
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            redis_instance = AsyncMock()
            mock_redis.return_value = redis_instance

            await svc.create_escalation(
                TEST_CONVERSATION_ID,
                EscalationTrigger.rag_failure,
                None,
                tenant,
            )

            redis_instance.publish.assert_called_once()
            call_args = redis_instance.publish.call_args
            assert call_args[0][0] == "rabat:escalations:new"

    @pytest.mark.asyncio
    async def test_create_escalation_audit_logged(self):
        """Creation d'escalade -> audit_service.log_action appele."""
        svc = _make_escalation_service()
        svc._gemini.generate_simple = AsyncMock(return_value="Resume")

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        session.add = MagicMock()
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            mock_redis.return_value.publish = AsyncMock()

            await svc.create_escalation(
                TEST_CONVERSATION_ID,
                EscalationTrigger.explicit_request,
                "Agent svp",
                tenant,
            )

        svc._audit.log_action.assert_called_once()
        audit_data = svc._audit.log_action.call_args[0][0]
        assert audit_data.action == "create"
        assert audit_data.resource_type == "escalation"

    @pytest.mark.asyncio
    async def test_assign_escalation_sets_assigned_status(self):
        """Assignation -> status=assigned, assigned_to=admin_id."""
        svc = _make_escalation_service()

        escalation_mock = MagicMock()
        escalation_mock.id = TEST_ESCALATION_ID
        escalation_mock.conversation_id = TEST_CONVERSATION_ID
        escalation_mock.status = EscalationStatus.pending

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = escalation_mock
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            mock_redis.return_value.publish = AsyncMock()

            result = await svc.assign_escalation(TEST_ESCALATION_ID, TEST_ADMIN_ID, tenant)

        assert result.status == EscalationStatus.assigned
        assert result.assigned_to == TEST_ADMIN_ID
        assert result.assigned_at is not None

    @pytest.mark.asyncio
    async def test_respond_via_whatsapp_creates_message(self):
        """Reponse agent -> message WhatsApp envoye + Message cree en DB."""
        svc = _make_escalation_service()
        svc._sender.send_text = AsyncMock(return_value="wamid.123")

        escalation_mock = MagicMock()
        escalation_mock.id = TEST_ESCALATION_ID
        escalation_mock.conversation_id = TEST_CONVERSATION_ID
        escalation_mock.status = EscalationStatus.assigned

        session = AsyncMock()
        # First execute: get escalation, second: get phone
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.scalar_one.return_value = escalation_mock
            else:
                mock_r.scalar_one.return_value = "+212600000001"
            return mock_r

        session.execute = AsyncMock(side_effect=_side_effect)
        session.add = MagicMock()

        tenant = _make_tenant_mock(session)

        wamid = await svc.respond_via_whatsapp(
            TEST_ESCALATION_ID, "Bonjour, voici l'info", TEST_ADMIN_ID, tenant
        )
        assert wamid == "wamid.123"
        svc._sender.send_text.assert_called_once()
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_transitions_to_in_progress(self):
        """Reponse depuis status assigned -> status in_progress."""
        svc = _make_escalation_service()
        svc._sender.send_text = AsyncMock(return_value="wamid.456")

        escalation_mock = MagicMock()
        escalation_mock.id = TEST_ESCALATION_ID
        escalation_mock.conversation_id = TEST_CONVERSATION_ID
        escalation_mock.status = EscalationStatus.assigned

        session = AsyncMock()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.scalar_one.return_value = escalation_mock
            else:
                mock_r.scalar_one.return_value = "+212600000001"
            return mock_r

        session.execute = AsyncMock(side_effect=_side_effect)
        session.add = MagicMock()

        tenant = _make_tenant_mock(session)

        await svc.respond_via_whatsapp(
            TEST_ESCALATION_ID, "Info", TEST_ADMIN_ID, tenant
        )
        assert escalation_mock.status == EscalationStatus.in_progress

    @pytest.mark.asyncio
    async def test_close_escalation_restores_active_conversation(self):
        """Cloture -> escalation status=resolved, conversation revient a 'active'."""
        svc = _make_escalation_service()
        svc._sender.send_text = AsyncMock()

        escalation_mock = MagicMock()
        escalation_mock.id = TEST_ESCALATION_ID
        escalation_mock.conversation_id = TEST_CONVERSATION_ID
        escalation_mock.status = EscalationStatus.in_progress

        session = AsyncMock()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.scalar_one.return_value = escalation_mock
            else:
                mock_r.scalar_one.return_value = "+212600000001"
            return mock_r

        session.execute = AsyncMock(side_effect=_side_effect)

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            mock_redis.return_value.publish = AsyncMock()

            result = await svc.close_escalation(
                TEST_ESCALATION_ID,
                "Probleme resolu par telephone",
                TEST_ADMIN_ID,
                tenant,
            )

        assert result.status == EscalationStatus.resolved
        assert result.resolution_notes == "Probleme resolu par telephone"
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_close_escalation_sends_closure_message(self):
        """Cloture -> message WhatsApp de cloture envoye."""
        from app.services.escalation.service import CLOSURE_MESSAGES

        svc = _make_escalation_service()

        escalation_mock = MagicMock()
        escalation_mock.id = TEST_ESCALATION_ID
        escalation_mock.conversation_id = TEST_CONVERSATION_ID
        escalation_mock.status = EscalationStatus.in_progress

        session = AsyncMock()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.scalar_one.return_value = escalation_mock
            else:
                mock_r.scalar_one.return_value = "+212600000001"
            return mock_r

        session.execute = AsyncMock(side_effect=_side_effect)

        tenant = _make_tenant_mock(session)

        with patch("app.services.escalation.service.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            mock_redis.return_value.publish = AsyncMock()

            await svc.close_escalation(
                TEST_ESCALATION_ID, "Resolu", TEST_ADMIN_ID, tenant, language="fr"
            )

        svc._sender.send_text.assert_called_once()
        call_args = svc._sender.send_text.call_args
        assert call_args[0][2] == CLOSURE_MESSAGES["fr"]

    @pytest.mark.asyncio
    async def test_generate_context_summary_calls_gemini(self):
        """Resume contextuel -> appel Gemini avec les derniers messages."""
        svc = _make_escalation_service()
        svc._gemini.generate_simple = AsyncMock(return_value="Resume: sujet principal...")

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [
            ("inbound", "Bonjour, j'ai un probleme"),
            ("outbound", "Bonjour, comment puis-je vous aider ?"),
        ]
        session.execute = AsyncMock(return_value=result_mock)

        tenant = _make_tenant_mock(session)

        summary = await svc.generate_context_summary(TEST_CONVERSATION_ID, tenant)
        assert summary == "Resume: sujet principal..."
        svc._gemini.generate_simple.assert_called_once()


# =====================================================================
# Trilingual Messages
# =====================================================================


class TestEscalationMessages:
    """Tests des messages trilingues."""

    def test_transition_messages_trilingual(self):
        """Messages de transition disponibles en FR, AR, EN."""
        from app.services.escalation.service import TRANSITION_MESSAGES

        assert len(TRANSITION_MESSAGES) == 3
        assert "fr" in TRANSITION_MESSAGES
        assert "ar" in TRANSITION_MESSAGES
        assert "en" in TRANSITION_MESSAGES

    def test_closure_messages_trilingual(self):
        """Messages de cloture disponibles en FR, AR, EN."""
        from app.services.escalation.service import CLOSURE_MESSAGES

        assert len(CLOSURE_MESSAGES) == 3
        assert "fr" in CLOSURE_MESSAGES
        assert "ar" in CLOSURE_MESSAGES
        assert "en" in CLOSURE_MESSAGES

    def test_already_escalated_messages_trilingual(self):
        """Messages 'deja escalade' disponibles en FR, AR, EN."""
        from app.services.escalation.service import ALREADY_ESCALATED_MESSAGES

        assert len(ALREADY_ESCALATED_MESSAGES) == 3
        assert "fr" in ALREADY_ESCALATED_MESSAGES
        assert "ar" in ALREADY_ESCALATED_MESSAGES
        assert "en" in ALREADY_ESCALATED_MESSAGES
