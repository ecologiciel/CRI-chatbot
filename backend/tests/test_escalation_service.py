"""Tests for the escalation service and LangGraph handler (Wave 15B).

Covers: imports, trigger-priority mapping, transition messages,
escalation detection, router routing, and singleton factory.
No database required — uses mocks and pure logic tests.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestEscalationImports:
    """Verify all escalation modules are importable."""

    def test_service_import(self):
        from app.services.escalation.service import EscalationService

        assert EscalationService is not None

    def test_singleton_factory_import(self):
        from app.services.escalation.service import get_escalation_service

        assert callable(get_escalation_service)

    def test_package_reexport(self):
        from app.services.escalation import (
            EscalationService,
            get_escalation_service,
        )

        assert EscalationService is not None
        assert callable(get_escalation_service)

    def test_handler_import(self):
        from app.services.orchestrator.escalation_handler import EscalationHandler

        assert EscalationHandler is not None

    def test_handler_singleton_import(self):
        from app.services.orchestrator.escalation_handler import (
            get_escalation_handler,
        )

        assert callable(get_escalation_handler)


# ---------------------------------------------------------------------------
# 2. Trigger → Priority mapping
# ---------------------------------------------------------------------------


class TestTriggerPriorityMapping:
    """Verify TRIGGER_PRIORITY_MAP covers all triggers with correct priorities."""

    def test_all_triggers_have_priority(self):
        from app.models.enums import EscalationTrigger
        from app.services.escalation.service import EscalationService

        mapping = EscalationService.TRIGGER_PRIORITY_MAP
        for trigger in EscalationTrigger:
            assert trigger in mapping, f"Missing mapping for {trigger.value}"

    def test_explicit_request_is_high(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.explicit_request]
            == EscalationPriority.high
        )

    def test_sensitive_topic_is_high(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.sensitive_topic]
            == EscalationPriority.high
        )

    def test_rag_failure_is_medium(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.rag_failure]
            == EscalationPriority.medium
        )

    def test_negative_feedback_is_medium(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.negative_feedback]
            == EscalationPriority.medium
        )

    def test_otp_timeout_is_low(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.otp_timeout]
            == EscalationPriority.low
        )

    def test_manual_is_medium(self):
        from app.models.enums import EscalationPriority, EscalationTrigger
        from app.services.escalation.service import EscalationService

        assert (
            EscalationService.TRIGGER_PRIORITY_MAP[EscalationTrigger.manual]
            == EscalationPriority.medium
        )


# ---------------------------------------------------------------------------
# 3. Transition messages
# ---------------------------------------------------------------------------


class TestTransitionMessages:
    """Verify trilingual transition and closure messages."""

    def test_transition_messages_cover_all_languages(self):
        from app.services.escalation.service import TRANSITION_MESSAGES

        assert set(TRANSITION_MESSAGES.keys()) == {"fr", "ar", "en"}

    def test_transition_messages_are_nonempty(self):
        from app.services.escalation.service import TRANSITION_MESSAGES

        for lang, msg in TRANSITION_MESSAGES.items():
            assert isinstance(msg, str), f"{lang} is not a string"
            assert len(msg) > 10, f"{lang} message is too short"

    def test_closure_messages_cover_all_languages(self):
        from app.services.escalation.service import CLOSURE_MESSAGES

        assert set(CLOSURE_MESSAGES.keys()) == {"fr", "ar", "en"}

    def test_already_escalated_messages_cover_all_languages(self):
        from app.services.escalation.service import ALREADY_ESCALATED_MESSAGES

        assert set(ALREADY_ESCALATED_MESSAGES.keys()) == {"fr", "ar", "en"}

    def test_messages_defined_in_service_module(self):
        """Transition and already-escalated messages are defined in service."""
        from app.services.escalation.service import (
            ALREADY_ESCALATED_MESSAGES,
            TRANSITION_MESSAGES,
        )

        # Handler uses deferred imports from the same module at runtime
        assert isinstance(TRANSITION_MESSAGES, dict)
        assert isinstance(ALREADY_ESCALATED_MESSAGES, dict)


# ---------------------------------------------------------------------------
# 4. Escalation detection (pure logic)
# ---------------------------------------------------------------------------


class TestDetectEscalation:
    """Test detect_escalation with mocked service (no DB/Redis)."""

    def _make_service(self):
        """Create an EscalationService with mocked dependencies."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services.escalation.service import EscalationService

        return EscalationService(
            gemini=MagicMock(),
            sender=MagicMock(),
            audit=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_detect_explicit_request(self):
        from app.models.enums import EscalationTrigger

        service = self._make_service()
        state = {"intent": "escalade", "query": "je veux parler a un agent"}
        result = await service.detect_escalation(state)
        assert result == EscalationTrigger.explicit_request

    @pytest.mark.asyncio
    async def test_detect_rag_failure(self):
        from app.models.enums import EscalationTrigger

        service = self._make_service()
        state = {
            "intent": "faq",
            "query": "question normale",
            "consecutive_low_confidence": 2,
        }
        result = await service.detect_escalation(state)
        assert result == EscalationTrigger.rag_failure

    @pytest.mark.asyncio
    async def test_detect_rag_failure_below_threshold(self):
        service = self._make_service()
        state = {
            "intent": "faq",
            "query": "question normale",
            "consecutive_low_confidence": 1,
        }
        result = await service.detect_escalation(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_none_when_normal(self):
        service = self._make_service()
        state = {
            "intent": "faq",
            "query": "quelle est la procedure",
            "confidence": 0.9,
            "consecutive_low_confidence": 0,
        }
        result = await service.detect_escalation(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_negative_feedback_pattern(self):
        from app.models.enums import EscalationTrigger

        service = self._make_service()
        state = {
            "intent": "faq",
            "query": "je veux parler a un conseiller",
            "confidence": 0.3,
            "consecutive_low_confidence": 0,
        }
        result = await service.detect_escalation(state)
        assert result == EscalationTrigger.negative_feedback


# ---------------------------------------------------------------------------
# 5. Router routing
# ---------------------------------------------------------------------------


class TestRouterRoutesEscalation:
    """Verify router sends escalade intent to escalation_handler."""

    def test_escalade_intent_routes_to_handler(self):
        from app.services.orchestrator.router import Router

        state = {"intent": "escalade", "is_safe": True}
        result = Router.route(state)
        assert result == "escalation_handler"

    def test_blocked_overrides_escalation(self):
        from app.services.orchestrator.router import Router

        state = {"intent": "escalade", "is_safe": False}
        result = Router.route(state)
        assert result == "blocked_response"


# ---------------------------------------------------------------------------
# 6. Service constants
# ---------------------------------------------------------------------------


class TestServiceConstants:
    """Verify service configuration constants."""

    def test_low_confidence_threshold(self):
        from app.services.escalation.service import EscalationService

        assert EscalationService.LOW_CONFIDENCE_THRESHOLD == 0.5

    def test_consecutive_failure_limit(self):
        from app.services.escalation.service import EscalationService

        assert EscalationService.CONSECUTIVE_FAILURE_LIMIT == 2

    def test_escalation_placeholder_removed_from_simple_nodes(self):
        """EscalationPlaceholder should no longer exist in simple_nodes."""
        import app.services.orchestrator.simple_nodes as sn

        assert not hasattr(sn, "EscalationPlaceholder")
