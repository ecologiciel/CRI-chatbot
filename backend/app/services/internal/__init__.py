"""Internal agent service — agent interne for whitelisted CRI employees."""

from app.services.internal.service import InternalAgentService, get_internal_agent_service

__all__ = ["InternalAgentService", "get_internal_agent_service"]
