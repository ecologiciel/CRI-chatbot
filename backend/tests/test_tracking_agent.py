"""Tests for TrackingAgent — LangGraph dossier tracking node (Wave 24B).

Covers:
- TrackingStateManager: Redis state get/set/clear + key format
- TrackingAgent step machine: idle, awaiting_identifier, otp_sent, authenticated
- Cancel/logout flows
- Rate limiting, max attempts, session expiry
- Anti-BOLA enforcement
- No Gemini calls during dossier data operations
- Trilingual messages
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import Language
from app.services.orchestrator.state import ConversationState
from app.services.orchestrator.tracking_agent import (
    MAX_OTP_ATTEMPTS,
    TrackingAgent,
    _extract_identifier,
    _is_cancel,
    _is_logout,
    _msg,
)
from app.services.orchestrator.tracking_state import (
    TRACKING_STATE_TTL,
    TrackingStateManager,
    TrackingStep,
    TrackingUserState,
)

# --- Fixtures ----------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)

TEST_PHONE = "+212612345678"


def _make_state(**overrides: object) -> ConversationState:
    """Create a minimal ConversationState for tracking tests."""
    state: ConversationState = {  # type: ignore[typeddict-item]
        "tenant_slug": "rabat",
        "phone": TEST_PHONE,
        "language": "fr",
        "intent": "suivi_dossier",
        "query": "je veux suivre mon dossier",
        "messages": [],
        "retrieved_chunks": [],
        "response": "",
        "chunk_ids": [],
        "confidence": 0.0,
        "is_safe": True,
        "guard_message": None,
        "incentive_state": {},
        "error": None,
        "consecutive_low_confidence": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _make_mock_dossier_read(
    numero: str = "2024-001",
    dossier_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock DossierRead."""
    mock = MagicMock()
    mock.id = dossier_id or uuid.uuid4()
    mock.numero = numero
    mock.statut = "en_cours"
    return mock


def _make_mock_dossier_detail(
    numero: str = "2024-001",
    dossier_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock DossierDetail."""
    mock = MagicMock()
    mock.id = dossier_id or uuid.uuid4()
    mock.numero = numero
    mock.statut = "en_cours"
    return mock


def _make_tracking_agent(
    otp_mock: AsyncMock | None = None,
    dossier_mock: MagicMock | None = None,
    state_mgr_mock: AsyncMock | None = None,
) -> tuple[TrackingAgent, AsyncMock, MagicMock, AsyncMock]:
    """Create a TrackingAgent with mocked dependencies.

    Returns:
        (agent, otp_service_mock, dossier_service_mock, state_mgr_mock)
    """
    otp = otp_mock or AsyncMock()
    dossier = dossier_mock or MagicMock()
    mgr = state_mgr_mock or AsyncMock()
    agent = TrackingAgent(
        otp_service=otp,
        dossier_service=dossier,
        state_manager=mgr,
    )
    return agent, otp, dossier, mgr


# =============================================================================
# TrackingStateManager tests
# =============================================================================


class TestTrackingStateManager:
    """Tests for Redis-backed state manager."""

    @pytest.mark.asyncio
    async def test_get_state_returns_default_when_no_redis_key(self) -> None:
        """No state in Redis → returns default idle TrackingUserState."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()
            state = await mgr.get_state(TEST_PHONE, TEST_TENANT)

        assert state.step == TrackingStep.idle
        assert state.identifier is None
        assert state.otp_attempts == 0
        assert state.session_token is None
        assert state.dossier_ids == []

    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self) -> None:
        """Persists and retrieves a state correctly."""
        stored: dict[str, str] = {}

        mock_redis = AsyncMock()

        async def mock_set(key: str, value: str, ex: int | None = None) -> None:
            stored[key] = value

        async def mock_get(key: str) -> str | None:
            return stored.get(key)

        mock_redis.set = mock_set
        mock_redis.get = mock_get

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()

            new_state = TrackingUserState(
                step=TrackingStep.otp_sent,
                identifier="2024-001",
                identifier_type="numero",
                otp_attempts=1,
            )
            await mgr.set_state(TEST_PHONE, new_state, TEST_TENANT)

            retrieved = await mgr.get_state(TEST_PHONE, TEST_TENANT)

        assert retrieved.step == TrackingStep.otp_sent
        assert retrieved.identifier == "2024-001"
        assert retrieved.identifier_type == "numero"
        assert retrieved.otp_attempts == 1

    @pytest.mark.asyncio
    async def test_clear_state_deletes_key(self) -> None:
        """clear_state calls Redis.delete with the correct key."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()
            await mgr.clear_state(TEST_PHONE, TEST_TENANT)

        expected_key = f"rabat:tracking_state:{TEST_PHONE}"
        mock_redis.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_redis_key_uses_tenant_prefix(self) -> None:
        """Key format is {slug}:tracking_state:{phone}."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()
            await mgr.get_state(TEST_PHONE, TEST_TENANT)

        expected_key = f"rabat:tracking_state:{TEST_PHONE}"
        mock_redis.get.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_set_state_uses_correct_ttl(self) -> None:
        """set_state stores JSON with TTL = TRACKING_STATE_TTL (1800s)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()
            state = TrackingUserState(step=TrackingStep.idle)
            await mgr.set_state(TEST_PHONE, state, TEST_TENANT)

        call_args = mock_redis.set.call_args
        assert call_args.kwargs.get("ex") == TRACKING_STATE_TTL or call_args[1].get("ex") == TRACKING_STATE_TTL
        # Verify JSON is valid
        raw_json = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("value")
        data = json.loads(raw_json)
        assert data["step"] == "idle"

    @pytest.mark.asyncio
    async def test_corrupted_redis_data_returns_default(self) -> None:
        """Corrupted JSON in Redis → returns default state (no crash)."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="not-valid-json{{{")

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()
            state = await mgr.get_state(TEST_PHONE, TEST_TENANT)

        assert state.step == TrackingStep.idle


# =============================================================================
# Helper function tests
# =============================================================================


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_extract_identifier_numero(self) -> None:
        result = _extract_identifier("mon dossier 2024-1234")
        assert result == ("2024-1234", "numero")

    def test_extract_identifier_numero_slash(self) -> None:
        result = _extract_identifier("dossier 2024/567")
        assert result == ("2024/567", "numero")

    def test_extract_identifier_cin(self) -> None:
        result = _extract_identifier("AB123456")
        assert result == ("AB123456", "cin")

    def test_extract_identifier_cin_lowercase(self) -> None:
        result = _extract_identifier("ab123456")
        assert result == ("AB123456", "cin")

    def test_extract_identifier_none(self) -> None:
        result = _extract_identifier("bonjour comment ça va")
        assert result is None

    def test_extract_identifier_prefers_numero_over_cin(self) -> None:
        result = _extract_identifier("dossier 2024-12345 CIN AB12345")
        assert result is not None
        assert result[1] == "numero"

    def test_is_cancel_french(self) -> None:
        assert _is_cancel("annuler") is True
        assert _is_cancel("je veux annuler") is True

    def test_is_cancel_arabic(self) -> None:
        assert _is_cancel("\u0627\u0644\u063a\u0627\u0621") is True

    def test_is_cancel_english(self) -> None:
        assert _is_cancel("cancel") is True

    def test_is_cancel_false(self) -> None:
        assert _is_cancel("mon dossier") is False

    def test_is_logout_french(self) -> None:
        assert _is_logout("terminer") is True

    def test_is_logout_english(self) -> None:
        assert _is_logout("done") is True

    def test_msg_returns_french_default(self) -> None:
        msg = _msg("ask_identifier", "fr")
        assert "dossier" in msg.lower()

    def test_msg_returns_arabic(self) -> None:
        msg = _msg("ask_identifier", "ar")
        assert "\u0645\u0644\u0641" in msg  # ملف

    def test_msg_returns_english(self) -> None:
        msg = _msg("ask_identifier", "en")
        assert "file" in msg.lower()

    def test_msg_format_substitution(self) -> None:
        msg = _msg("otp_invalid", "fr", remaining="2")
        assert "2" in msg


# =============================================================================
# TrackingAgent — Idle step
# =============================================================================


class TestTrackingAgentIdle:
    """Tests for the idle step."""

    @pytest.mark.asyncio
    async def test_idle_asks_for_identifier(self) -> None:
        """In idle state with no identifier in query → ask for identifier."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        state = _make_state(query="je veux suivre mon dossier")
        result = await agent.handle(state, TEST_TENANT)

        assert "dossier" in result["response"].lower()
        mgr.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_idle_with_identifier_in_query_skips_to_otp(self) -> None:
        """Idle with identifier in query → lookup + OTP generation."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        mock_detail = _make_mock_dossier_detail("2024-001")
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        otp.is_rate_limited = AsyncMock(return_value=False)
        otp.generate_otp = AsyncMock(return_value="123456")

        state = _make_state(query="suivi dossier 2024-001")
        result = await agent.handle(state, TEST_TENANT)

        # Should get OTP sent message
        assert "6" in result["response"] or "code" in result["response"].lower()
        otp.generate_otp.assert_called_once()


# =============================================================================
# TrackingAgent — Awaiting identifier step
# =============================================================================


class TestTrackingAgentAwaitingIdentifier:
    """Tests for the awaiting_identifier step."""

    @pytest.mark.asyncio
    async def test_valid_numero_triggers_otp(self) -> None:
        """Valid dossier numero → OTP generated → transition to otp_sent."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )
        mgr.set_state = AsyncMock()

        mock_detail = _make_mock_dossier_detail("2024-555")
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        otp.is_rate_limited = AsyncMock(return_value=False)
        otp.generate_otp = AsyncMock(return_value="654321")

        state = _make_state(query="2024-555")
        result = await agent.handle(state, TEST_TENANT)

        otp.generate_otp.assert_called_once_with(TEST_PHONE, TEST_TENANT)
        # Verify state was persisted with otp_sent step
        set_call = mgr.set_state.call_args
        saved_state: TrackingUserState = set_call[0][1]
        assert saved_state.step == TrackingStep.otp_sent

    @pytest.mark.asyncio
    async def test_valid_cin_triggers_otp(self) -> None:
        """Valid CIN → lookup by phone → OTP generated."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )
        mgr.set_state = AsyncMock()

        dossier.get_dossier_by_numero = AsyncMock(return_value=None)
        mock_read = _make_mock_dossier_read()
        dossier.get_dossiers_by_phone = AsyncMock(return_value=[mock_read])
        otp.is_rate_limited = AsyncMock(return_value=False)
        otp.generate_otp = AsyncMock(return_value="111222")

        state = _make_state(query="AB123456")
        result = await agent.handle(state, TEST_TENANT)

        otp.generate_otp.assert_called_once()
        dossier.get_dossiers_by_phone.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_identifier_returns_not_found(self) -> None:
        """Unknown numero → 'no dossier found' message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )

        dossier.get_dossier_by_numero = AsyncMock(return_value=None)

        state = _make_state(query="2024-999")
        result = await agent.handle(state, TEST_TENANT)

        assert "aucun" in result["response"].lower() or "no file" in result["response"].lower()
        otp.generate_otp.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_format_asks_again(self) -> None:
        """Unrecognized input → repeat ask_identifier message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )

        state = _make_state(query="hello world")
        result = await agent.handle(state, TEST_TENANT)

        assert "dossier" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_rate_limited_returns_message(self) -> None:
        """Rate limited → returns rate limit message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )

        mock_detail = _make_mock_dossier_detail()
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        otp.is_rate_limited = AsyncMock(return_value=True)

        state = _make_state(query="2024-001")
        result = await agent.handle(state, TEST_TENANT)

        assert "15 min" in result["response"].lower() or "tentatives" in result["response"].lower()
        otp.generate_otp.assert_not_called()


# =============================================================================
# TrackingAgent — OTP sent step
# =============================================================================


class TestTrackingAgentOtpSent:
    """Tests for the otp_sent step."""

    @pytest.mark.asyncio
    async def test_correct_otp_authenticates(self) -> None:
        """Correct OTP → session created → dossier list returned."""
        dossier_id = uuid.uuid4()
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.otp_sent,
                identifier="2024-001",
                otp_attempts=0,
            ),
        )
        mgr.set_state = AsyncMock()

        otp.verify_otp = AsyncMock(return_value=True)
        otp.create_dossier_session = AsyncMock(return_value="session_token_hex")

        mock_read = _make_mock_dossier_read("2024-001", dossier_id)
        dossier.get_dossiers_by_phone = AsyncMock(return_value=[mock_read])
        mock_detail = _make_mock_dossier_detail("2024-001", dossier_id)
        dossier.get_dossier_with_bola_check = AsyncMock(return_value=mock_detail)
        dossier.format_dossier_for_whatsapp = MagicMock(
            return_value="\U0001f4cb Dossier N\u00b0 2024-001\n\U0001f4ca Statut : En cours",
        )

        state = _make_state(query="123456")
        result = await agent.handle(state, TEST_TENANT)

        assert "2024-001" in result["response"]
        otp.verify_otp.assert_called_once_with(TEST_PHONE, "123456", TEST_TENANT)
        otp.create_dossier_session.assert_called_once()

        # Verify state transition to authenticated
        saved_state: TrackingUserState = mgr.set_state.call_args[0][1]
        assert saved_state.step == TrackingStep.authenticated
        assert saved_state.session_token == "session_token_hex"

    @pytest.mark.asyncio
    async def test_wrong_otp_increments_attempts(self) -> None:
        """Wrong OTP → attempts incremented → error message with remaining count."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.otp_sent,
                otp_attempts=0,
            ),
        )
        mgr.set_state = AsyncMock()
        otp.verify_otp = AsyncMock(return_value=False)

        state = _make_state(query="999999")
        result = await agent.handle(state, TEST_TENANT)

        assert "incorrect" in result["response"].lower() or "\u274c" in result["response"]
        # Verify attempts incremented
        saved_state: TrackingUserState = mgr.set_state.call_args[0][1]
        assert saved_state.otp_attempts == 1

    @pytest.mark.asyncio
    async def test_max_attempts_resets_to_idle(self) -> None:
        """3rd wrong attempt → reset to idle + max attempts message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.otp_sent,
                otp_attempts=2,  # This will be the 3rd attempt
            ),
        )
        mgr.clear_state = AsyncMock()
        otp.verify_otp = AsyncMock(return_value=False)

        state = _make_state(query="999999")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()
        assert "maximum" in result["response"].lower() or "\u26a0" in result["response"]

    @pytest.mark.asyncio
    async def test_non_digit_input_asks_for_code(self) -> None:
        """Text input instead of digits → ask for OTP code."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.otp_sent),
        )

        state = _make_state(query="bonjour")
        result = await agent.handle(state, TEST_TENANT)

        assert "6" in result["response"] or "code" in result["response"].lower()
        otp.verify_otp.assert_not_called()


# =============================================================================
# TrackingAgent — Authenticated step
# =============================================================================


class TestTrackingAgentAuthenticated:
    """Tests for the authenticated step."""

    @pytest.mark.asyncio
    async def test_valid_session_lists_dossiers(self) -> None:
        """Valid session → returns dossier list."""
        dossier_id = uuid.uuid4()
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="valid_token",
            ),
        )

        otp.validate_dossier_session = AsyncMock(return_value=True)

        mock_read = _make_mock_dossier_read("2024-001", dossier_id)
        dossier.get_dossiers_by_phone = AsyncMock(return_value=[mock_read])
        mock_detail = _make_mock_dossier_detail("2024-001", dossier_id)
        dossier.get_dossier_with_bola_check = AsyncMock(return_value=mock_detail)
        dossier.format_dossier_for_whatsapp = MagicMock(
            return_value="\U0001f4cb Dossier 2024-001",
        )

        state = _make_state(query="mes dossiers")
        result = await agent.handle(state, TEST_TENANT)

        assert "2024-001" in result["response"]
        otp.validate_dossier_session.assert_called_once_with(
            TEST_PHONE, "valid_token", TEST_TENANT,
        )

    @pytest.mark.asyncio
    async def test_session_expired_resets(self) -> None:
        """Expired session → clear state + session expired message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="expired_token",
            ),
        )
        mgr.clear_state = AsyncMock()
        otp.validate_dossier_session = AsyncMock(return_value=False)

        state = _make_state(query="mes dossiers")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()
        assert "expir" in result["response"].lower() or "\u23f0" in result["response"]

    @pytest.mark.asyncio
    async def test_logout_clears_session(self) -> None:
        """Logout keyword → invalidate session + clear state."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="valid_token",
            ),
        )
        mgr.clear_state = AsyncMock()
        otp.validate_dossier_session = AsyncMock(return_value=True)
        otp.invalidate_session = AsyncMock()

        state = _make_state(query="terminer")
        result = await agent.handle(state, TEST_TENANT)

        otp.invalidate_session.assert_called_once_with(TEST_PHONE, TEST_TENANT)
        mgr.clear_state.assert_called_once()
        assert "session" in result["response"].lower() or "\U0001f44b" in result["response"]

    @pytest.mark.asyncio
    async def test_specific_dossier_query(self) -> None:
        """Ask for specific dossier by numero in authenticated state."""
        dossier_id = uuid.uuid4()
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="valid_token",
            ),
        )

        otp.validate_dossier_session = AsyncMock(return_value=True)

        mock_detail = _make_mock_dossier_detail("2024-999", dossier_id)
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        dossier.get_dossier_with_bola_check = AsyncMock(return_value=mock_detail)
        dossier.format_dossier_for_whatsapp = MagicMock(
            return_value="\U0001f4cb Dossier 2024-999",
        )

        state = _make_state(query="dossier 2024-999")
        result = await agent.handle(state, TEST_TENANT)

        assert "2024-999" in result["response"]
        dossier.get_dossier_with_bola_check.assert_called_once_with(
            TEST_TENANT, dossier_id, TEST_PHONE,
        )

    @pytest.mark.asyncio
    async def test_bola_check_denies_unauthorized(self) -> None:
        """Anti-BOLA: unauthorized dossier access → 'not found' (no info leak)."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="valid_token",
            ),
        )

        otp.validate_dossier_session = AsyncMock(return_value=True)

        mock_detail = _make_mock_dossier_detail("2024-888")
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        # BOLA check fails
        dossier.get_dossier_with_bola_check = AsyncMock(
            side_effect=Exception("UnauthorizedDossierAccess"),
        )

        state = _make_state(query="dossier 2024-888")
        result = await agent.handle(state, TEST_TENANT)

        # Should get a generic "not found" — no info leak about dossier existence
        assert "aucun" in result["response"].lower() or "no file" in result["response"].lower()


# =============================================================================
# Cancel flow
# =============================================================================


class TestTrackingAgentCancel:
    """Tests for the universal cancel flow."""

    @pytest.mark.asyncio
    async def test_cancel_from_awaiting_identifier(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )
        mgr.clear_state = AsyncMock()

        state = _make_state(query="annuler")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()
        assert "annul" in result["response"].lower() or "cancel" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_cancel_from_otp_sent(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.otp_sent),
        )
        mgr.clear_state = AsyncMock()

        state = _make_state(query="cancel")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_in_arabic(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.otp_sent),
        )
        mgr.clear_state = AsyncMock()

        state = _make_state(query="\u0627\u0644\u063a\u0627\u0621", language="ar")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()
        # Arabic cancel message
        assert "\u0627\u0644\u0625\u0644\u063a\u0627\u0621" in result["response"]

    @pytest.mark.asyncio
    async def test_cancel_does_not_trigger_in_idle(self) -> None:
        """Cancel keywords in idle state are ignored (treated as normal query)."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        state = _make_state(query="annuler")
        result = await agent.handle(state, TEST_TENANT)

        # Should not clear state — should ask for identifier instead
        mgr.clear_state.assert_not_called()


# =============================================================================
# No Gemini calls
# =============================================================================


class TestNoGeminiCalls:
    """Verify that no LLM/Gemini service is called during dossier tracking."""

    @pytest.mark.asyncio
    async def test_no_gemini_in_full_flow(self) -> None:
        """Complete flow idle→otp_sent→authenticated without any Gemini call."""
        dossier_id = uuid.uuid4()
        agent, otp, dossier, mgr = _make_tracking_agent()

        # Step 1: idle → awaiting_identifier (with identifier in query)
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        mock_detail = _make_mock_dossier_detail("2024-001", dossier_id)
        dossier.get_dossier_by_numero = AsyncMock(return_value=mock_detail)
        otp.is_rate_limited = AsyncMock(return_value=False)
        otp.generate_otp = AsyncMock(return_value="123456")

        state = _make_state(query="suivi 2024-001")
        await agent.handle(state, TEST_TENANT)

        # Step 2: otp_sent → authenticated
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.otp_sent,
                identifier="2024-001",
                otp_attempts=0,
            ),
        )
        otp.verify_otp = AsyncMock(return_value=True)
        otp.create_dossier_session = AsyncMock(return_value="token")

        mock_read = _make_mock_dossier_read("2024-001", dossier_id)
        dossier.get_dossiers_by_phone = AsyncMock(return_value=[mock_read])
        dossier.get_dossier_with_bola_check = AsyncMock(return_value=mock_detail)
        dossier.format_dossier_for_whatsapp = MagicMock(return_value="Dossier 2024-001")

        state = _make_state(query="123456")
        await agent.handle(state, TEST_TENANT)

        # Verify: no Gemini import or call anywhere in TrackingAgent
        # The agent module does NOT import GeminiService at all
        import app.services.orchestrator.tracking_agent as ta_module

        # Check that no attribute referencing Gemini exists
        module_source = ta_module.__file__ or ""
        assert "GeminiService" not in open(module_source).read()


# =============================================================================
# Multilingual messages
# =============================================================================


class TestMultilingual:
    """Test that responses are in the correct language."""

    @pytest.mark.asyncio
    async def test_french_response(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        state = _make_state(query="suivi", language="fr")
        result = await agent.handle(state, TEST_TENANT)

        # French ask_identifier message
        assert "dossier" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_arabic_response(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        state = _make_state(query="\u0645\u062a\u0627\u0628\u0639\u0629", language="ar")
        result = await agent.handle(state, TEST_TENANT)

        # Arabic ask_identifier message contains ملف (file)
        assert "\u0645\u0644\u0641" in result["response"]

    @pytest.mark.asyncio
    async def test_english_response(self) -> None:
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.idle),
        )
        mgr.set_state = AsyncMock()

        state = _make_state(query="track", language="en")
        result = await agent.handle(state, TEST_TENANT)

        assert "file" in result["response"].lower()


# =============================================================================
# Error handling
# =============================================================================


class TestErrorHandling:
    """Test graceful error handling."""

    @pytest.mark.asyncio
    async def test_redis_error_returns_fallback(self) -> None:
        """Redis failure → graceful error message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(side_effect=Exception("Redis connection failed"))

        state = _make_state(query="suivi")
        result = await agent.handle(state, TEST_TENANT)

        assert "erreur" in result["response"].lower() or "error" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_dossier_service_error_returns_fallback(self) -> None:
        """DossierService failure → graceful error message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(step=TrackingStep.awaiting_identifier),
        )

        dossier.get_dossier_by_numero = AsyncMock(
            side_effect=Exception("DB connection failed"),
        )

        state = _make_state(query="2024-001")
        result = await agent.handle(state, TEST_TENANT)

        assert "erreur" in result["response"].lower() or "error" in result["response"].lower()
