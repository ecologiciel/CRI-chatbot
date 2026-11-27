"""A suppressed provider call must not be turned into a fallback send."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.services.orchestrator.feedback_collector import FeedbackCollector
from app.services.orchestrator.graph import _wrap_simple_node, _wrap_tenant_node, run_conversation
from app.services.orchestrator.state import IntentType
from app.services.whatsapp.outbound_fence import OutboundSupersededError


@pytest.mark.asyncio
async def test_feedback_and_graph_wrappers_propagate_suppression():
    tenant = TenantContext(uuid.uuid4(), "fixture", "Fixture", "active", None)
    sender = AsyncMock()
    sender.send_buttons.side_effect = OutboundSupersededError("stopped")
    collector = FeedbackCollector(sender)
    state = {"intent": IntentType.FAQ, "phone": "fixture", "language": "fr"}
    with pytest.raises(OutboundSupersededError):
        await collector.collect(state, tenant)
    with patch("app.services.orchestrator.graph._reconstruct_tenant", return_value=tenant):
        with pytest.raises(OutboundSupersededError):
            await _wrap_tenant_node(collector.collect, "feedback")(state)
    with pytest.raises(OutboundSupersededError):
        await _wrap_simple_node(AsyncMock(side_effect=OutboundSupersededError("stopped")), "simple")(state)
    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=OutboundSupersededError("stopped"))
    with patch("app.services.orchestrator.graph.get_conversation_graph", return_value=graph):
        with pytest.raises(OutboundSupersededError):
            await run_conversation(tenant, "fixture", "question")
