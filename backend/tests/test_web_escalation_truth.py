"""The anonymous browser demo must not promise an unavailable handoff."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.tenant import TenantContext
from app.services.orchestrator.escalation_handler import EscalationHandler
from app.services.orchestrator.graph import run_conversation
from app.services.rag.prompts import PromptTemplates


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "ar", "en"])
async def test_web_escalation_gives_official_contact_without_creating_case(language):
    service = AsyncMock()
    tenant = TenantContext(uuid.uuid4(), "prospect", "Institution", "active", None)
    result = await EscalationHandler(service).handle(
        {"channel": "web", "language": language, "intent": "escalade"}, tenant
    )

    assert result["response"] == PromptTemplates.get_message("web_escalation_unavailable", language)
    assert result["sources"] == []
    assert result["chunk_ids"] == []
    service.create_escalation.assert_not_awaited()
    service.lookup_active_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_conversation_graph_receives_web_channel():
    graph = AsyncMock()
    graph.ainvoke.return_value = {"response": "test"}
    tenant = TenantContext(uuid.uuid4(), "prospect", "Institution", "active", None)
    with patch("app.services.orchestrator.graph.get_conversation_graph", return_value=graph):
        await run_conversation(tenant, "web-synthetic", "question", channel="web")
    assert graph.ainvoke.await_args.args[0]["channel"] == "web"
