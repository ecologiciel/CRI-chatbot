"""Tests for ResponseValidator and FeedbackCollector."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.services.guardrails.output_guard import OutputGuardResult
from app.services.orchestrator.feedback_collector import (
    FEEDBACK_BUTTONS,
    FeedbackCollector,
)
from app.services.orchestrator.response_validator import ResponseValidator
from app.services.orchestrator.state import ConversationState, IntentType
from app.services.rag.prompts import PromptTemplates


# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config={
        "phone_number_id": "111222333",
        "access_token": "test_token",
        "verify_token": "test_verify",
    },
)


def _make_state(**overrides) -> ConversationState:
    """Create a minimal ConversationState for testing."""
    state: ConversationState = {
        "tenant_slug": "rabat",
        "phone": "+212600000000",
        "language": "fr",
        "intent": "faq",
        "query": "Comment créer une SARL ?",
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# --- ResponseValidator tests ---


class TestResponseValidator:
    """ResponseValidator test suite."""

    @pytest.mark.asyncio
    async def test_validator_clean_response(self):
        """Clean response with high confidence → response unchanged."""
        mock_guard = AsyncMock()
        mock_guard.check = AsyncMock(
            return_value=OutputGuardResult(
                is_valid=True,
                cleaned_text="Pour créer une SARL, il faut...",
                issues=[],
                pii_masked_count=0,
                confidence_ok=True,
            ),
        )

        validator = ResponseValidator(output_guard=mock_guard)
        state = _make_state(
            response="Pour créer une SARL, il faut...",
            confidence=0.9,
        )

        result = await validator.validate(state, TEST_TENANT)

        assert result["response"] == "Pour créer une SARL, il faut..."
        mock_guard.check.assert_awaited_once_with(
            "Pour créer une SARL, il faut...", 0.9, "fr",
        )

    @pytest.mark.asyncio
    async def test_validator_masks_pii(self):
        """Response with CIN → PII masked in output."""
        mock_guard = AsyncMock()
        mock_guard.check = AsyncMock(
            return_value=OutputGuardResult(
                is_valid=True,
                cleaned_text="Votre dossier ****** est en cours.",
                issues=["pii_found: 1 item(s) masked"],
                pii_masked_count=1,
                confidence_ok=True,
            ),
        )

        validator = ResponseValidator(output_guard=mock_guard)
        state = _make_state(
            response="Votre dossier AB12345 est en cours.",
            confidence=0.9,
        )

        result = await validator.validate(state, TEST_TENANT)

        assert "AB12345" not in result["response"]
        assert "******" in result["response"]

    @pytest.mark.asyncio
    async def test_validator_low_confidence_disclaimer(self):
        """Low confidence → disclaimer appended to response."""
        disclaimer_text = (
            "\n\n_Cette information est fournie à titre indicatif. Pour des "
            "renseignements officiels, veuillez contacter votre CRI directement._"
        )
        mock_guard = AsyncMock()
        mock_guard.check = AsyncMock(
            return_value=OutputGuardResult(
                is_valid=True,
                cleaned_text="Réponse partielle." + disclaimer_text,
                issues=["low_confidence: 0.50 < 0.7"],
                pii_masked_count=0,
                confidence_ok=False,
            ),
        )

        validator = ResponseValidator(output_guard=mock_guard)
        state = _make_state(response="Réponse partielle.", confidence=0.5)

        result = await validator.validate(state, TEST_TENANT)

        assert "titre indicatif" in result["response"]

    @pytest.mark.asyncio
    async def test_validator_empty_response_skipped(self):
        """Empty response → no-op, guard not called."""
        mock_guard = AsyncMock()
        validator = ResponseValidator(output_guard=mock_guard)
        state = _make_state(response="")

        result = await validator.validate(state, TEST_TENANT)

        assert result == {}
        mock_guard.check.assert_not_awaited()


# --- FeedbackCollector tests ---


class TestFeedbackCollector:
    """FeedbackCollector test suite."""

    @pytest.mark.asyncio
    async def test_feedback_buttons_sent_for_faq(self):
        """Intent=faq → send_buttons called with 3 localized buttons."""
        mock_sender = AsyncMock()
        mock_sender.send_buttons = AsyncMock(return_value="wamid.feedback")

        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(intent=IntentType.FAQ, phone="+212600000001")

        await collector.collect(state, TEST_TENANT)

        mock_sender.send_buttons.assert_awaited_once()
        call_args = mock_sender.send_buttons.call_args

        # Verify tenant and phone
        assert call_args[0][0] is TEST_TENANT  # tenant
        assert call_args[0][1] == "+212600000001"  # to

        # Verify body text
        expected_body = PromptTemplates.get_message("feedback_request", "fr")
        assert call_args[0][2] == expected_body  # body_text

        # Verify buttons
        buttons = call_args[0][3]
        assert len(buttons) == 3
        assert buttons[0]["id"] == "feedback_positive"
        assert buttons[1]["id"] == "feedback_negative"
        assert buttons[2]["id"] == "feedback_unclear"

    @pytest.mark.asyncio
    async def test_feedback_skipped_for_greeting(self):
        """Intent=salutation → send_buttons NOT called."""
        mock_sender = AsyncMock()
        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(intent=IntentType.SALUTATION)

        await collector.collect(state, TEST_TENANT)

        mock_sender.send_buttons.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_feedback_skipped_for_hors_perimetre(self):
        """Intent=hors_perimetre → send_buttons NOT called."""
        mock_sender = AsyncMock()
        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(intent=IntentType.HORS_PERIMETRE)

        await collector.collect(state, TEST_TENANT)

        mock_sender.send_buttons.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_feedback_send_failure_non_blocking(self):
        """send_buttons raises → no error propagated, returns empty dict."""
        mock_sender = AsyncMock()
        mock_sender.send_buttons = AsyncMock(
            side_effect=RuntimeError("WhatsApp API timeout"),
        )

        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(intent=IntentType.FAQ, phone="+212600000001")

        # Should NOT raise
        result = await collector.collect(state, TEST_TENANT)

        assert result == {}

    @pytest.mark.asyncio
    async def test_feedback_skipped_no_phone(self):
        """No phone number → skip feedback silently."""
        mock_sender = AsyncMock()
        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(intent=IntentType.FAQ, phone="")

        await collector.collect(state, TEST_TENANT)

        mock_sender.send_buttons.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_feedback_arabic_buttons(self):
        """Arabic language → Arabic button titles."""
        mock_sender = AsyncMock()
        mock_sender.send_buttons = AsyncMock(return_value="wamid.feedback")

        collector = FeedbackCollector(sender=mock_sender)
        state = _make_state(
            intent=IntentType.FAQ,
            language="ar",
            phone="+212600000001",
        )

        await collector.collect(state, TEST_TENANT)

        call_args = mock_sender.send_buttons.call_args
        buttons = call_args[0][3]
        assert buttons[0]["title"] == "مفيد"
        assert buttons[1]["title"] == "غير مفيد"
