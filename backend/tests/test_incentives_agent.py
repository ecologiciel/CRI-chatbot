"""Tests for IncentivesAgent — LangGraph incentives navigation node."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.tenant import TenantContext
from app.services.orchestrator.incentives_agent import _FALLBACK, IncentivesAgent
from app.services.orchestrator.state import ConversationState

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
        "intent": "incitations",
        "query": "",
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


def _make_incentives_agent(mock_service=None):
    """Create IncentivesAgent with a mocked IncentivesService."""
    service = mock_service or AsyncMock()
    return IncentivesAgent(incentives=service), service


# --- Tests ---


class TestIncentivesAgent:
    """IncentivesAgent test suite."""

    @pytest.mark.asyncio
    async def test_handle_delegates_to_service(self):
        """Agent delegates to IncentivesService.handle with correct args."""
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(
            return_value={"response": "Menu affiché", "error": None},
        )

        agent, service = _make_incentives_agent(mock_service)
        state = _make_state()

        await agent.handle(state, TEST_TENANT)

        service.handle.assert_awaited_once_with(state, TEST_TENANT)

    @pytest.mark.asyncio
    async def test_handle_returns_service_result(self):
        """Agent returns the result from IncentivesService unchanged."""
        expected = {
            "response": "Choisissez une catégorie d'incitations :",
            "error": None,
        }
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(return_value=expected)

        agent, _ = _make_incentives_agent(mock_service)
        state = _make_state()

        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == expected["response"]
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_handle_error_returns_fallback_french(self):
        """Service raises → agent catches, returns French fallback."""
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(
            side_effect=RuntimeError("DB connection failed"),
        )

        agent, _ = _make_incentives_agent(mock_service)
        state = _make_state(language="fr")

        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == _FALLBACK["fr"]
        assert result["error"] == "DB connection failed"

    @pytest.mark.asyncio
    async def test_handle_error_returns_fallback_arabic(self):
        """Service raises → agent catches, returns Arabic fallback."""
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(
            side_effect=ValueError("Invalid category"),
        )

        agent, _ = _make_incentives_agent(mock_service)
        state = _make_state(language="ar")

        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == _FALLBACK["ar"]
        assert result["error"] == "Invalid category"

    @pytest.mark.asyncio
    async def test_handle_error_defaults_to_french(self):
        """Missing language in state → defaults to French fallback."""
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(
            side_effect=RuntimeError("Unexpected"),
        )

        agent, _ = _make_incentives_agent(mock_service)
        # State without language key
        state = _make_state()
        del state["language"]  # type: ignore[misc]

        result = await agent.handle(state, TEST_TENANT)

        assert result["response"] == _FALLBACK["fr"]
        assert result["error"] == "Unexpected"

    @pytest.mark.asyncio
    async def test_handle_with_incentive_state(self):
        """Agent passes incentive_state through to the service."""
        inc_state = {
            "current_category_id": str(uuid.uuid4()),
            "navigation_path": ["cat1"],
        }
        mock_service = AsyncMock()
        mock_service.handle = AsyncMock(
            return_value={"response": "Sous-catégories :", "error": None},
        )

        agent, service = _make_incentives_agent(mock_service)
        state = _make_state(incentive_state=inc_state)

        await agent.handle(state, TEST_TENANT)

        # Verify the full state (including incentive_state) was passed
        call_state = service.handle.call_args[0][0]
        assert call_state["incentive_state"] == inc_state
