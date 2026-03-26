"""ConversationService — manage conversation lifecycle, message persistence, and history.

Conversations auto-close after 30 minutes of inactivity. On each new inbound
message, the service checks whether the contact's active conversation has
timed out and, if so, closes it and creates a fresh one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select

from app.core.tenant import TenantContext
from app.models.conversation import Conversation, Message
from app.models.enums import (
    AgentType,
    ConversationStatus,
    MessageDirection,
    MessageType,
)

logger = structlog.get_logger()

# 30-minute inactivity timeout (configurable per CLAUDE.md §5)
CONVERSATION_TIMEOUT = 1800  # seconds


class ConversationService:
    """Manage conversations: create, resume, close, persist messages."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="conversation_service")

    # ── Conversation lifecycle ──

    async def get_or_create(
        self,
        tenant: TenantContext,
        contact_id: uuid.UUID,
        agent_type: AgentType = AgentType.public,
    ) -> Conversation:
        """Get the active conversation for a contact or create a new one.

        A conversation is considered expired if its last message (or
        ``started_at`` when no messages exist) is older than
        ``CONVERSATION_TIMEOUT`` seconds.

        Args:
            tenant: Tenant context for DB session.
            contact_id: UUID of the contact.
            agent_type: Type of agent handling the conversation.

        Returns:
            Active or newly created Conversation ORM object.
        """
        async with tenant.db_session() as session:
            # Find the most recent active conversation for this contact
            result = await session.execute(
                select(Conversation)
                .where(
                    Conversation.contact_id == contact_id,
                    Conversation.status == ConversationStatus.active,
                )
                .order_by(Conversation.started_at.desc())
                .limit(1),
            )
            existing = result.scalar_one_or_none()

            if existing is not None:
                # Check last message timestamp for timeout
                last_ts = await self._get_last_message_time(session, existing.id)
                reference_time = last_ts or existing.started_at
                now = datetime.now(UTC)

                if (now - reference_time) > timedelta(seconds=CONVERSATION_TIMEOUT):
                    # Timed out — close old, create new
                    existing.status = ConversationStatus.ended
                    existing.ended_at = now
                    self._logger.info(
                        "conversation_timed_out",
                        tenant=tenant.slug,
                        conversation_id=str(existing.id),
                    )
                else:
                    # Still active — resume
                    return existing

            # Create new conversation
            conversation = Conversation(
                contact_id=contact_id,
                agent_type=agent_type,
                status=ConversationStatus.active,
                started_at=datetime.now(UTC),
            )
            session.add(conversation)
            await session.flush()

            self._logger.info(
                "conversation_created",
                tenant=tenant.slug,
                conversation_id=str(conversation.id),
                contact_id=str(contact_id),
            )
            return conversation

    async def close_conversation(
        self,
        tenant: TenantContext,
        conversation_id: uuid.UUID,
    ) -> None:
        """Explicitly close a conversation.

        Args:
            tenant: Tenant context for DB session.
            conversation_id: UUID of the conversation to close.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id),
            )
            conversation = result.scalar_one_or_none()
            if conversation is not None and conversation.status == ConversationStatus.active:
                conversation.status = ConversationStatus.ended
                conversation.ended_at = datetime.now(UTC)

    # ── Message persistence ──

    async def add_message(
        self,
        tenant: TenantContext,
        conversation_id: uuid.UUID,
        direction: MessageDirection,
        msg_type: MessageType,
        content: str | None,
        media_url: str | None = None,
        chunk_ids: list[str] | None = None,
        whatsapp_message_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Persist a message to the tenant database.

        Args:
            tenant: Tenant context for DB session.
            conversation_id: UUID of the parent conversation.
            direction: inbound or outbound.
            msg_type: text, image, audio, interactive, etc.
            content: Message text content.
            media_url: MinIO path for media messages.
            chunk_ids: RAG chunk IDs (outbound, for feedback correlation).
            whatsapp_message_id: wamid for dedup/status tracking.
            metadata: Additional metadata (intent, language, confidence).

        Returns:
            Created Message ORM object with populated ID.
        """
        async with tenant.db_session() as session:
            message = Message(
                conversation_id=conversation_id,
                direction=direction,
                type=msg_type,
                content=content,
                media_url=media_url,
                chunk_ids=chunk_ids or [],
                whatsapp_message_id=whatsapp_message_id,
                metadata_=metadata,
                timestamp=datetime.now(UTC),
            )
            session.add(message)
            await session.flush()
            return message

    # ── History retrieval ──

    async def get_history(
        self,
        tenant: TenantContext,
        conversation_id: uuid.UUID,
        limit: int = 10,
    ) -> list[dict]:
        """Get conversation history formatted for LangGraph.

        Returns recent messages as ``[{"role": "user"|"assistant", "content": str}]``,
        ordered oldest-first for natural conversation context.
        Messages with no text content (media-only) are skipped.

        Args:
            tenant: Tenant context for DB session.
            conversation_id: UUID of the conversation.
            limit: Maximum number of messages to return.

        Returns:
            List of role/content dicts for ``run_conversation(conversation_history=...)``.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.desc())
                .limit(limit),
            )
            messages = list(result.scalars().all())

        # Reverse for oldest-first order
        messages.reverse()

        history: list[dict] = []
        for msg in messages:
            if not msg.content:
                continue
            role = "user" if msg.direction == MessageDirection.inbound else "assistant"
            history.append({"role": role, "content": msg.content})
        return history

    # ── Metadata update ──

    async def update_metadata(
        self,
        tenant: TenantContext,
        conversation_id: uuid.UUID,
        metadata_update: dict,
    ) -> None:
        """Merge new keys into conversation metadata (JSONB).

        Reassigns the dict to trigger SQLAlchemy JSONB change detection.

        Args:
            tenant: Tenant context for DB session.
            conversation_id: UUID of the conversation.
            metadata_update: Keys to merge into existing metadata.
        """
        async with tenant.db_session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id),
            )
            conversation = result.scalar_one_or_none()
            if conversation is not None:
                current = dict(conversation.metadata_ or {})
                current.update(metadata_update)
                conversation.metadata_ = current

    # ── Internal helpers ──

    @staticmethod
    async def _get_last_message_time(
        session,
        conversation_id: uuid.UUID,
    ) -> datetime | None:
        """Get the timestamp of the most recent message in a conversation."""
        result = await session.execute(
            select(func.max(Message.timestamp)).where(
                Message.conversation_id == conversation_id,
            ),
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_conversation_service: ConversationService | None = None


def get_conversation_service() -> ConversationService:
    """Get or create the ConversationService singleton."""
    global _conversation_service  # noqa: PLW0603
    if _conversation_service is None:
        _conversation_service = ConversationService()
    return _conversation_service
