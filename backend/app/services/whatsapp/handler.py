"""MessageHandler — end-to-end message processing pipeline.

Orchestrates the full flow for every inbound WhatsApp message:
dedup → rate limit → quota → contact → conversation → content extraction →
feedback routing → LangGraph → persistence → response → quota tracking.

This is the central integration point connecting all Wave 1-8 services.
"""

from __future__ import annotations

import contextlib
import unicodedata
import uuid
from enum import Enum

import structlog

from app.core.metrics import RATE_LIMIT_TRIGGERED, WHATSAPP_MESSAGES
from app.core.redis import get_redis
from app.core.tenant import TenantContext
from app.models.conversation import Message
from app.models.enums import (
    AgentType,
    FeedbackRating,
    Language,
    MessageDirection,
    MessageType,
    OptInStatus,
)
from app.schemas.feedback import FeedbackCreate
from app.schemas.whatsapp import ContactInfo, IncomingMessage
from app.services.contact.segmentation import SegmentationService, get_segmentation_service
from app.services.contact.service import get_contact_service
from app.services.conversation.service import get_conversation_service
from app.services.feedback.service import get_feedback_service
from app.services.rag.prompts import PromptTemplates
from app.services.whatsapp.media import WhatsAppMediaHandler
from app.services.whatsapp.outbound_fence import OutboundSupersededError
from app.services.whatsapp.privacy import NoticeResult, get_privacy_notice_service
from app.services.whatsapp.sender import WhatsAppSenderService
from app.services.whatsapp.session import WhatsAppSessionManager

logger = structlog.get_logger()

# ── Per-user rate limiting (CLAUDE.md §9.3) ──
USER_RATE_LIMIT_MAX = 10
USER_RATE_LIMIT_WINDOW = 60  # seconds

# ── Feedback button ID → FeedbackRating mapping ──
FEEDBACK_BUTTON_MAP: dict[str, FeedbackRating] = {
    "feedback_positive": FeedbackRating.positive,
    "feedback_negative": FeedbackRating.negative,
    "feedback_unclear": FeedbackRating.question,
}

# ── Feedback acknowledgment message keys (per rating) ──
FEEDBACK_ACK_KEYS: dict[FeedbackRating, str] = {
    FeedbackRating.positive: "feedback_ack_positive",
    FeedbackRating.negative: "feedback_ack_negative",
    FeedbackRating.question: "feedback_ack_question",
}


class HandlingOutcome(str, Enum):
    accepted = "accepted"
    uncertain = "uncertain"
    suppressed = "suppressed"


class MessageHandler:
    """End-to-end message processing: webhook → LangGraph → WhatsApp response."""

    def __init__(self) -> None:
        self._logger = logger.bind(service="message_handler")
        self._session_manager = WhatsAppSessionManager()
        self._sender = WhatsAppSenderService()
        self._media_handler = WhatsAppMediaHandler()
        self._contact_service = get_contact_service()
        self._conversation_service = get_conversation_service()
        self._feedback_service = get_feedback_service()
        self._privacy_service = get_privacy_notice_service()

    async def handle_message(
        self,
        tenant: TenantContext,
        msg: IncomingMessage,
        contacts: list[ContactInfo] | None,
        *,
        durable: bool = False,
    ) -> HandlingOutcome:
        """Process a single inbound WhatsApp message end-to-end.

        The durable mode bypasses the legacy Redis deduplicator because its
        caller must already hold a fenced database claim. It reports ambiguous
        outcomes for operator review and never sends a second error message.
        Provider acceptance is not a delivery receipt.

        Args:
            tenant: Resolved tenant context.
            msg: Parsed incoming message.
            contacts: Contact info from the webhook payload.
        """
        phone = msg.from_
        wamid = msg.id
        uncertain = False

        # Opt-out must not be blocked by Redis deduplication, rate limits,
        # quotas, privacy-notice delivery or conversation creation.
        if msg.type == "text" and msg.text and SegmentationService.is_stop_command(msg.text.body):
            try:
                contact = await self._contact_service.get_or_create(
                    tenant, phone, _extract_sender_name(contacts, phone)
                )
                confirmed = await self._handle_stop_request(tenant, phone, contact)
            except OutboundSupersededError:
                return HandlingOutcome.suppressed
            except Exception as exc:
                self._logger.error(
                    "stop_command_failed",
                    tenant=tenant.slug,
                    phone_last4=_mask_phone(phone),
                    error_type=type(exc).__name__,
                )
                return HandlingOutcome.uncertain
            return HandlingOutcome.accepted if confirmed else HandlingOutcome.uncertain

        try:
            # 1. Dedup — already-processed messages are silently skipped
            if not durable and await self._session_manager.is_duplicate_message(tenant, wamid):
                self._logger.debug("message_duplicate_skipped", wamid=wamid, tenant=tenant.slug)
                return HandlingOutcome.uncertain

            # 2. Per-user rate limit (10 msg/min)
            if await self._check_user_rate_limit(tenant, phone):
                RATE_LIMIT_TRIGGERED.labels(tenant=tenant.slug, level="user").inc()
                self._logger.warning(
                    "user_rate_limited",
                    tenant=tenant.slug,
                    phone_last4=_mask_phone(phone),
                )
                sent = await self._sender.send_text(
                    tenant,
                    phone,
                    PromptTemplates.get_message("rate_limit_user", "fr"),
                )
                return HandlingOutcome.accepted if sent else HandlingOutcome.uncertain

            # 3. Quota check
            quota = await self._session_manager.check_quota(tenant)
            if quota.is_exhausted:
                self._logger.warning("tenant_quota_exhausted", tenant=tenant.slug)
                sent = await self._sender.send_text(
                    tenant,
                    phone,
                    PromptTemplates.get_message("quota_exhausted", "fr"),
                )
                return HandlingOutcome.accepted if sent else HandlingOutcome.uncertain

            # 4. Get or create contact
            sender_name = _extract_sender_name(contacts, phone)
            contact = await self._contact_service.get_or_create(
                tenant,
                phone,
                sender_name,
            )

            # 4.5 CNDP privacy notice — first contact (loi 09-08, Art. 9)
            try:
                notice = await self._privacy_service.send_privacy_notice(
                    tenant,
                    phone,
                    language=contact.language.value,
                )
                if durable and notice != NoticeResult.accepted:
                    uncertain = True
            except OutboundSupersededError:
                raise
            except Exception:
                uncertain = True

            # 5. Get or create conversation (30min inactivity timeout)
            conversation = await self._conversation_service.get_or_create(
                tenant,
                contact.id,
                AgentType.public,
            )

            # 6. Extract content from the message
            content, media_url, msg_type = await self._extract_content(tenant, msg)

            # 6.5 STOP command opt-out (CNDP §9.9)
            if content and SegmentationService.is_stop_command(content):
                confirmed = await self._handle_stop_request(tenant, phone, contact)
                return (
                    HandlingOutcome.accepted
                    if confirmed and not uncertain
                    else HandlingOutcome.uncertain
                )

            # 7. Feedback routing — interactive buttons starting with "feedback_"
            if self._is_feedback_reply(msg):
                confirmed = await self._handle_feedback(tenant, msg, conversation.id, phone)
                return (
                    HandlingOutcome.accepted
                    if confirmed and not uncertain
                    else HandlingOutcome.uncertain
                )

            if self._is_source_command(content):
                confirmed = await self._handle_source_command(
                    tenant, conversation.id, phone, content, wamid
                )
                return (
                    HandlingOutcome.accepted
                    if confirmed and not uncertain
                    else HandlingOutcome.uncertain
                )

            # 8. Mark as read (blue ticks) — non-critical
            try:
                await self._sender.mark_as_read(tenant, wamid)
            except Exception:
                self._logger.warning("mark_as_read_failed", wamid=wamid)

            # 9. Persist inbound message
            WHATSAPP_MESSAGES.labels(
                tenant=tenant.slug,
                direction="inbound",
                type=msg_type.value,
            ).inc()
            await self._conversation_service.add_message(
                tenant,
                conversation.id,
                MessageDirection.inbound,
                msg_type,
                content,
                media_url=media_url,
                whatsapp_message_id=wamid,
            )

            # 10. Update WhatsApp session (24h window)
            try:
                await self._session_manager.get_or_create_session(tenant, phone)
            except Exception:
                self._logger.warning("session_update_failed", tenant=tenant.slug)
                uncertain = True

            # 11. Get conversation history for LangGraph context
            try:
                history = await self._conversation_service.get_history(
                    tenant,
                    conversation.id,
                    limit=10,
                )
            except Exception:
                history = []
                uncertain = True

            # 12. Run LangGraph orchestrator
            conv_metadata = conversation.metadata_ or {}
            incentive_state = conv_metadata.get("incentive_state")

            # Pre-fetch tracking state from Redis for IntentDetector
            tracking_state_str: str | None = None
            try:
                from app.services.orchestrator.tracking_state import TrackingStateManager

                ts = await TrackingStateManager().get_state(phone, tenant)
                if ts.step.value != "idle":
                    tracking_state_str = ts.step.value
            except Exception:
                self._logger.warning("tracking_state_prefetch_failed", tenant=tenant.slug)
                uncertain = True

            from app.services.orchestrator.graph import run_conversation

            result = await run_conversation(
                tenant=tenant,
                phone=phone,
                query=content or "",
                conversation_history=history,
                incentive_state=incentive_state,
                conversation_id=str(conversation.id),
                tracking_state=tracking_state_str,
            )
            if result.get("error"):
                uncertain = True

            response_text = result.get("response", "")
            if not response_text:
                response_text = PromptTemplates.get_message("no_answer", "fr")
                uncertain = True

            # 13. Send response via WhatsApp
            out_wamid = None
            try:
                out_wamid = await self._sender.send_text(tenant, phone, response_text)
            except OutboundSupersededError:
                return HandlingOutcome.uncertain if uncertain else HandlingOutcome.suppressed
            except Exception as send_err:
                uncertain = True
                self._logger.error(
                    "send_response_failed",
                    error_type=type(send_err).__name__,
                    tenant=tenant.slug,
                )

            # 14. Persist outbound message
            try:
                await self._conversation_service.add_message(
                    tenant,
                    conversation.id,
                    MessageDirection.outbound,
                    MessageType.text,
                    response_text,
                    chunk_ids=result.get("chunk_ids", []),
                    whatsapp_message_id=out_wamid,
                    metadata={
                        "intent": result.get("intent"),
                        "language": result.get("language"),
                        "confidence": result.get("confidence"),
                        "sources": result.get("sources", []),
                        # A timeout or malformed provider response can occur
                        # after acceptance, so do not claim definitive failure.
                        "delivery_state": "unconfirmed" if not out_wamid else "accepted",
                    },
                )
            except Exception as persist_err:
                uncertain = True
                self._logger.error(
                    "persist_outbound_failed",
                    error_type=type(persist_err).__name__,
                    tenant=tenant.slug,
                )

            # 15. Track quota (only if actually sent)
            if out_wamid:
                WHATSAPP_MESSAGES.labels(
                    tenant=tenant.slug,
                    direction="outbound",
                    type="text",
                ).inc()
                try:
                    await self._session_manager.increment_quota(tenant)
                except Exception:
                    self._logger.warning("quota_increment_failed", tenant=tenant.slug)
                    uncertain = True

            # 16. Update conversation metadata
            try:
                await self._conversation_service.update_metadata(
                    tenant,
                    conversation.id,
                    {
                        "last_intent": result.get("intent"),
                        "last_language": result.get("language"),
                        "incentive_state": result.get("incentive_state", {}),
                    },
                )
            except Exception:
                self._logger.warning("metadata_update_failed", tenant=tenant.slug)
                uncertain = True

            # 17. Update contact language if detected differs
            detected_lang = result.get("language")
            if detected_lang and detected_lang != contact.language.value:
                try:
                    lang_enum = Language(detected_lang)
                    await self._contact_service.update_language(
                        tenant,
                        contact.id,
                        lang_enum,
                    )
                except (ValueError, Exception):
                    uncertain = True

            self._logger.info(
                "message_processed_e2e",
                tenant=tenant.slug,
                phone_last4=_mask_phone(phone),
                intent=result.get("intent"),
                language=result.get("language"),
                confidence=result.get("confidence"),
            )
            if not out_wamid:
                uncertain = True
            return HandlingOutcome.uncertain if uncertain else HandlingOutcome.accepted

        except OutboundSupersededError:
            return HandlingOutcome.uncertain if uncertain else HandlingOutcome.suppressed
        except Exception as exc:
            self._logger.error(
                "e2e_processing_failed",
                error_type=type(exc).__name__,
                tenant=tenant.slug,
                phone_last4=_mask_phone(phone),
            )
            # Best-effort error message to user
            if not durable:
                with contextlib.suppress(Exception):
                    await self._sender.send_text(
                        tenant,
                        phone,
                        PromptTemplates.get_message("error_generic", "fr"),
                    )
            return HandlingOutcome.uncertain

    async def _handle_stop_request(self, tenant: TenantContext, phone: str, contact) -> bool:
        opted_out = await get_segmentation_service().process_stop_command(tenant, phone)
        if not opted_out and contact.opt_in_status != OptInStatus.opted_out:
            return False
        lang = contact.language.value if contact.language else "fr"
        messages = {
            "fr": "Votre demande de désinscription a été enregistrée.",
            "ar": "تم تسجيل طلب إلغاء الاشتراك الخاص بك.",
            "en": "Your unsubscribe request has been recorded.",
        }
        return bool(await self._sender.send_text(tenant, phone, messages.get(lang, messages["fr"])))

    # ── Content extraction ──

    @staticmethod
    def _is_source_command(content: str | None) -> bool:
        if not content:
            return False
        normalized = (
            unicodedata.normalize("NFKD", content)
            .encode("ascii", "ignore")
            .decode()
            .strip()
            .lower()
        )
        return normalized == "source"

    async def _handle_source_command(
        self,
        tenant: TenantContext,
        conversation_id: uuid.UUID,
        phone: str,
        content: str | None,
        wamid: str,
    ) -> bool:
        """Persist a `Source` request and answer from local message metadata only."""
        await self._conversation_service.add_message(
            tenant,
            conversation_id,
            MessageDirection.inbound,
            MessageType.text,
            content,
            whatsapp_message_id=wamid,
        )
        sources = await self._conversation_service.get_latest_sources(tenant, conversation_id)
        response = PromptTemplates.format_sources_message(sources)
        out_wamid = await self._sender.send_text(tenant, phone, response)
        await self._conversation_service.add_message(
            tenant,
            conversation_id,
            MessageDirection.outbound,
            MessageType.text,
            response,
            whatsapp_message_id=out_wamid,
            metadata={"sources_response": True, "sources": sources},
        )
        return bool(out_wamid)

    async def _extract_content(
        self,
        tenant: TenantContext,
        msg: IncomingMessage,
    ) -> tuple[str | None, str | None, MessageType]:
        """Extract text content, media_url, and message type.

        Returns:
            Tuple of (content_text, media_url_or_none, MessageType).
        """
        if msg.type == "text" and msg.text:
            return msg.text.body, None, MessageType.text

        if msg.type == "image" and msg.image:
            media_result = await self._media_handler.process_media(
                tenant,
                msg.image.id,
                msg.image.mime_type,
            )
            caption = msg.image.caption or ""
            if media_result.success:
                text = f"{caption} {media_result.extracted_text}".strip()
            else:
                text = caption or None
            return (
                text,
                media_result.minio_path if media_result.success else None,
                MessageType.image,
            )

        if msg.type == "audio" and msg.audio:
            media_result = await self._media_handler.process_media(
                tenant,
                msg.audio.id,
                msg.audio.mime_type,
            )
            if media_result.success:
                return media_result.extracted_text, media_result.minio_path, MessageType.audio
            return None, None, MessageType.audio

        if msg.type == "interactive" and msg.interactive:
            reply = msg.interactive.button_reply or msg.interactive.list_reply
            if reply:
                return reply.title, None, MessageType.interactive
            return None, None, MessageType.interactive

        if msg.type == "button" and msg.button:
            return msg.button.text, None, MessageType.interactive

        # Unsupported message type — use type name as fallback
        return msg.type, None, MessageType.text

    # ── Feedback detection and handling ──

    @staticmethod
    def _is_feedback_reply(msg: IncomingMessage) -> bool:
        """Check if the message is a feedback button reply."""
        if msg.type == "interactive" and msg.interactive:
            reply = msg.interactive.button_reply
            if reply and reply.id.startswith("feedback_"):
                return True
        return False

    async def _handle_feedback(
        self,
        tenant: TenantContext,
        msg: IncomingMessage,
        conversation_id: uuid.UUID,
        phone: str,
    ) -> bool:
        """Process a feedback button click.

        Finds the last outbound message in the conversation and creates
        feedback for it. Sends an acknowledgment message to the user.
        """
        reply = msg.interactive.button_reply  # type: ignore[union-attr]
        rating = FEEDBACK_BUTTON_MAP.get(reply.id)
        if rating is None:
            return False

        # Find the last outbound message to attach feedback to
        from sqlalchemy import select

        async with tenant.db_session() as session:
            result = await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == MessageDirection.outbound,
                )
                .order_by(Message.timestamp.desc())
                .limit(1),
            )
            last_outbound = result.scalar_one_or_none()

        recorded = False
        if last_outbound:
            feedback_data = FeedbackCreate(
                message_id=last_outbound.id,
                rating=rating,
            )
            try:
                await self._feedback_service.create_feedback(tenant, feedback_data)
                recorded = True
            except Exception as exc:
                self._logger.error(
                    "feedback_creation_failed",
                    error_type=type(exc).__name__,
                    tenant=tenant.slug,
                )

        # Send acknowledgment
        ack_key = FEEDBACK_ACK_KEYS.get(rating, "feedback_ack_positive")
        ack_text = PromptTemplates.get_message(ack_key, "fr")
        try:
            acknowledged = await self._sender.send_text(tenant, phone, ack_text)
        except OutboundSupersededError:
            raise
        except Exception:
            return False
        return recorded and bool(acknowledged)

    # ── Rate limiting ──

    @staticmethod
    async def _check_user_rate_limit(tenant: TenantContext, phone: str) -> bool:
        """Check per-user rate limit (10 msg/min).

        Returns True if the user should be rate-limited (reject).
        """
        redis = get_redis()
        key = f"{tenant.redis_prefix}:rl:user:{phone}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, USER_RATE_LIMIT_WINDOW)
        return count > USER_RATE_LIMIT_MAX


# ── Module-level helpers ──


def _mask_phone(phone: str) -> str:
    """Mask phone number for logging (PII protection)."""
    return phone[-4:] if len(phone) >= 4 else "***"


def _extract_sender_name(
    contacts: list[ContactInfo] | None,
    phone: str,
) -> str | None:
    """Extract sender name from webhook contact info."""
    if contacts:
        for contact in contacts:
            if contact.wa_id == phone:
                return contact.profile.get("name")
    return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_message_handler: MessageHandler | None = None


def get_message_handler() -> MessageHandler:
    """Get or create the MessageHandler singleton."""
    global _message_handler  # noqa: PLW0603
    if _message_handler is None:
        _message_handler = MessageHandler()
    return _message_handler
