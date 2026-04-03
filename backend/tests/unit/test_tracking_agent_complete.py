"""Completion tests for TrackingAgent — Wave 29B.

Adds edge cases NOT in test_tracking_agent.py (Wave 24B):
- CIN with single letter prefix
- Authenticated but zero dossiers
- Cancel from otp_sent with non-zero attempts
- State manager with concurrent tenants (key isolation)
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.services.orchestrator.tracking_agent import (
    TrackingAgent,
    _extract_identifier,
)
from app.services.orchestrator.tracking_state import (
    TrackingStateManager,
    TrackingStep,
    TrackingUserState,
)

TEST_PHONE = "+212612345678"

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_state(**overrides: object) -> dict:
    state = {
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
    state.update(overrides)
    return state


def _make_tracking_agent(
    otp_mock=None, dossier_mock=None, state_mgr_mock=None,
):
    otp = otp_mock or AsyncMock()
    dossier = dossier_mock or MagicMock()
    mgr = state_mgr_mock or AsyncMock()
    agent = TrackingAgent(
        otp_service=otp, dossier_service=dossier, state_manager=mgr,
    )
    return agent, otp, dossier, mgr


# -- Tests ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.phase3
class TestIdentifierComplete:
    """Identifier extraction edge cases."""

    def test_cin_single_letter_prefix(self) -> None:
        """CIN with 1-letter prefix (e.g., B123456) should be recognized."""
        result = _extract_identifier("mon CIN est B123456")
        assert result is not None
        assert result[0] == "B123456"
        assert result[1] == "cin"


@pytest.mark.unit
@pytest.mark.phase3
class TestAuthenticatedComplete:
    """Authenticated state edge cases."""

    @pytest.mark.asyncio
    async def test_authenticated_no_dossiers_found(self) -> None:
        """Authenticated but phone has zero dossiers → informative message."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.authenticated,
                session_token="valid_token",
            ),
        )

        otp.validate_dossier_session = AsyncMock(return_value=True)
        dossier.get_dossiers_by_phone = AsyncMock(return_value=[])

        state = _make_state(query="mes dossiers")
        result = await agent.handle(state, TEST_TENANT)

        # Should indicate no dossiers found, not crash
        assert result["response"] != ""
        assert result.get("error") is None


@pytest.mark.unit
@pytest.mark.phase3
class TestCancelComplete:
    """Cancel flow edge case."""

    @pytest.mark.asyncio
    async def test_otp_sent_cancel_with_attempts_clears_state(self) -> None:
        """Cancel from otp_sent with attempts > 0 still clears state."""
        agent, otp, dossier, mgr = _make_tracking_agent()
        mgr.get_state = AsyncMock(
            return_value=TrackingUserState(
                step=TrackingStep.otp_sent,
                otp_attempts=2,  # Had failed attempts before cancelling
            ),
        )
        mgr.clear_state = AsyncMock()

        state = _make_state(query="annuler")
        result = await agent.handle(state, TEST_TENANT)

        mgr.clear_state.assert_called_once()
        assert "annul" in result["response"].lower() or "cancel" in result["response"].lower()


@pytest.mark.unit
@pytest.mark.phase3
class TestStateManagerComplete:
    """State manager tenant isolation edge case."""

    @pytest.mark.asyncio
    async def test_concurrent_tenants_different_keys(self) -> None:
        """Two tenants accessing same phone produce different Redis keys."""
        tenant_a = TenantContext(
            id=uuid.uuid4(), slug="alpha", name="CRI Alpha",
            status="active", whatsapp_config=None,
        )
        tenant_b = TenantContext(
            id=uuid.uuid4(), slug="beta", name="CRI Beta",
            status="active", whatsapp_config=None,
        )

        stored: dict[str, str] = {}

        async def mock_set(key: str, value: str, ex: int | None = None) -> None:
            stored[key] = value

        async def mock_get(key: str) -> str | None:
            return stored.get(key)

        mock_redis = AsyncMock()
        mock_redis.set = mock_set
        mock_redis.get = mock_get

        with patch(
            "app.services.orchestrator.tracking_state.get_redis",
            return_value=mock_redis,
        ):
            mgr = TrackingStateManager()

            # Set state for alpha
            state_a = TrackingUserState(
                step=TrackingStep.otp_sent,
                identifier="2024-001",
            )
            await mgr.set_state(TEST_PHONE, state_a, tenant_a)

            # Get state for beta → should be default idle (not alpha's state)
            state_b = await mgr.get_state(TEST_PHONE, tenant_b)

        assert state_b.step == TrackingStep.idle
        assert state_b.identifier is None

        # Verify different keys
        assert "alpha:tracking_state:" in list(stored.keys())[0]
        assert f"beta:tracking_state:{TEST_PHONE}" not in stored
