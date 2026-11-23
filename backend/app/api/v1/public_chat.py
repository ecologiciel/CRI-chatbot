"""Anonymous browser chat for explicitly enabled demonstration tenants."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.core.tenant import TenantContext, TenantResolver
from app.models.enums import AgentType, Language, MessageDirection, MessageType
from app.models.tenant import Tenant
from app.schemas.public_chat import (
    PublicChatRequest,
    PublicChatResponse,
    PublicSessionResponse,
    PublicSource,
)
from app.services.contact.service import get_contact_service
from app.services.conversation.service import get_conversation_service
from app.services.orchestrator.graph import run_conversation

router = APIRouter(prefix="/public", tags=["public-chat"])

COOKIE_NAME = "demo_chat_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_DISCLAIMER = (
    "Prototype de démonstration non officiel. Les réponses reposent sur une sélection "
    "de sources publiques et ne remplacent pas les informations officielles de l’institution."
)


async def _resolve_public_tenant(slug: str) -> tuple[TenantContext, Tenant]:
    """Resolve only tenants that deliberately enabled the web demo channel."""
    tenant_context = await TenantResolver.from_slug(slug)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_context.id))
        tenant = result.scalar_one_or_none()

    if tenant is None or not tenant.public_config.get("web_enabled", False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Démo introuvable")
    return tenant_context, tenant


async def _check_rate_limit(tenant: TenantContext, session_id: str) -> None:
    redis = get_redis()
    key = f"{tenant.redis_prefix}:rl:web:{session_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    if count > RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Veuillez patienter une minute avant d’envoyer un nouveau message.",
        )


@router.post("/{slug}/session", response_model=PublicSessionResponse)
async def create_session(slug: str, response: Response) -> PublicSessionResponse:
    """Create a pseudonymous browser session for an enabled demo tenant."""
    tenant, _ = await _resolve_public_tenant(slug)
    session_id = secrets.token_urlsafe(24)
    redis = get_redis()
    await redis.setex(
        f"{tenant.redis_prefix}:web_session:{session_id}",
        SESSION_TTL_SECONDS,
        json.dumps({"tenant": tenant.slug}),
    )
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        max_age=SESSION_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="strict",
        path=f"/api/v1/public/{slug}",
    )
    return PublicSessionResponse(tenant_slug=slug, expires_in_seconds=SESSION_TTL_SECONDS)


@router.post("/{slug}/messages", response_model=PublicChatResponse)
async def send_message(
    slug: str,
    payload: PublicChatRequest,
    demo_chat_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> PublicChatResponse:
    """Persist one browser turn and execute the tenant-scoped RAG graph."""
    tenant, tenant_record = await _resolve_public_tenant(slug)
    if not demo_chat_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session de démonstration requise")

    redis = get_redis()
    session_raw = await redis.get(f"{tenant.redis_prefix}:web_session:{demo_chat_session}")
    if not session_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expirée")
    try:
        session_data = json.loads(session_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide") from exc
    if session_data.get("tenant") != tenant.slug:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session non autorisée")

    await _check_rate_limit(tenant, demo_chat_session)
    language = Language(payload.language) if payload.language else Language.fr
    contacts = get_contact_service()
    conversations = get_conversation_service()
    contact = await contacts.get_or_create_web_session(tenant, demo_chat_session, language)
    conversation = await conversations.get_or_create(tenant, contact.id, AgentType.public)

    await conversations.add_message(
        tenant, conversation.id, MessageDirection.inbound, MessageType.text, payload.message
    )
    history = await conversations.get_history(tenant, conversation.id, limit=10)
    result = await run_conversation(
        tenant=tenant,
        phone=contact.phone,
        query=payload.message,
        conversation_history=history,
        incentive_state=(conversation.metadata_ or {}).get("incentive_state"),
        conversation_id=str(conversation.id),
    )

    answer = result.get("response") or "Je ne dispose pas d’une information fiable pour répondre à cette question."
    raw_sources = result.get("sources", [])
    sources = [PublicSource.model_validate(source) for source in raw_sources[:3] if isinstance(source, dict)]
    await conversations.add_message(
        tenant,
        conversation.id,
        MessageDirection.outbound,
        MessageType.text,
        answer,
        chunk_ids=result.get("chunk_ids", []),
        metadata={
            "intent": result.get("intent"),
            "language": result.get("language"),
            "confidence": result.get("confidence"),
            "sources": [source.model_dump() for source in sources],
            "channel": "web",
        },
    )
    await conversations.update_metadata(
        tenant,
        conversation.id,
        {"incentive_state": result.get("incentive_state", {}), "channel": "web"},
    )

    disclaimer = tenant_record.public_config.get("disclaimer", DEFAULT_DISCLAIMER)
    return PublicChatResponse(
        answer=answer,
        language=result.get("language", language.value),
        sources=sources,
        disclaimer=disclaimer,
    )
