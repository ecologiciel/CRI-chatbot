"""End-to-end tests for the WhatsApp → LangGraph → Response pipeline.

Tests cover the full MessageHandler flow: dedup, rate limiting, quota,
contact/conversation management, media processing, feedback routing,
LangGraph execution, message persistence, and error handling.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import (
    AgentType,
    FeedbackRating,
    Language,
    MessageDirection,
)
from app.schemas.whatsapp import (
    ContactInfo,
    IncomingMessage,
    InteractiveContent,
    InteractiveReply,
    MediaContent,
    TextContent,
)
from app.services.whatsapp.session import QuotaInfo

# ── Test tenant ──

TEST_TENANT = TenantContext(
    id=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config={
        "phone_number_id": "111222333",
        "access_token": "test_token",
        "annual_message_limit": 100_000,
    },
)

TEST_PHONE = "+212600000001"
TEST_WAMID = "wamid.HBgNMjEyNjAwMDAwMDAx"

# Patch target for run_conversation (lazy import inside handle_message)
RUN_CONV_PATH = "app.services.orchestrator.graph.run_conversation"


# ── Factories ──


def _make_text_message(
    body: str = "Comment créer une SARL ?",
    wamid: str = TEST_WAMID,
    phone: str = TEST_PHONE,
) -> IncomingMessage:
    return IncomingMessage(
        id=wamid,
        **{"from": phone},
        timestamp=str(int(datetime.now(UTC).timestamp())),
        type="text",
        text=TextContent(body=body),
    )


def _make_image_message(
    wamid: str = TEST_WAMID,
    phone: str = TEST_PHONE,
) -> IncomingMessage:
    return IncomingMessage(
        id=wamid,
        **{"from": phone},
        timestamp=str(int(datetime.now(UTC).timestamp())),
        type="image",
        image=MediaContent(id="media_img_123", mime_type="image/jpeg", caption="Mon document"),
    )


def _make_audio_message(
    wamid: str = TEST_WAMID,
    phone: str = TEST_PHONE,
) -> IncomingMessage:
    return IncomingMessage(
        id=wamid,
        **{"from": phone},
        timestamp=str(int(datetime.now(UTC).timestamp())),
        type="audio",
        audio=MediaContent(id="media_aud_456", mime_type="audio/ogg"),
    )


def _make_feedback_message(
    button_id: str = "feedback_positive",
    wamid: str = TEST_WAMID,
    phone: str = TEST_PHONE,
) -> IncomingMessage:
    return IncomingMessage(
        id=wamid,
        **{"from": phone},
        timestamp=str(int(datetime.now(UTC).timestamp())),
        type="interactive",
        interactive=InteractiveContent(
            type="button_reply",
            button_reply=InteractiveReply(id=button_id, title="Utile"),
        ),
    )


def _make_contacts(phone: str = TEST_PHONE, name: str = "Ahmed") -> list[ContactInfo]:
    return [ContactInfo(profile={"name": name}, wa_id=phone)]


def _make_run_result(**overrides) -> dict:
    return {
        "response": "Pour créer une SARL, vous devez déposer un dossier au CRI.",
        "intent": "faq",
        "language": "fr",
        "chunk_ids": ["chunk_1", "chunk_2"],
        "confidence": 0.85,
        "incentive_state": {},
        "error": None,
        **overrides,
    }


def _make_mock_contact(**overrides):
    contact = MagicMock()
    contact.id = overrides.get("id", uuid.uuid4())
    contact.phone = overrides.get("phone", TEST_PHONE)
    contact.name = overrides.get("name", "Ahmed")
    contact.language = overrides.get("language", Language.fr)
    return contact


def _make_mock_conversation(**overrides):
    conv = MagicMock()
    conv.id = overrides.get("id", uuid.uuid4())
    conv.contact_id = overrides.get("contact_id", uuid.uuid4())
    conv.status = overrides.get("status", "active")
    conv.metadata_ = overrides.get("metadata_", {})
    conv.started_at = overrides.get("started_at", datetime.now(UTC))
    return conv


def _make_mock_message(**overrides):
    msg = MagicMock()
    msg.id = overrides.get("id", uuid.uuid4())
    msg.conversation_id = overrides.get("conversation_id", uuid.uuid4())
    msg.direction = overrides.get("direction", MessageDirection.outbound)
    msg.content = overrides.get("content", "Réponse test")
    msg.chunk_ids = overrides.get("chunk_ids", ["chunk_1"])
    msg.timestamp = overrides.get("timestamp", datetime.now(UTC))
    return msg


def _make_quota(is_exhausted: bool = False) -> QuotaInfo:
    return QuotaInfo(
        monthly_count=100,
        annual_count=50_000 if not is_exhausted else 100_000,
        annual_limit=100_000,
        remaining=50_000 if not is_exhausted else 0,
        is_warning=False,
        is_exhausted=is_exhausted,
    )


def _make_mock_db_session(query_result=None):
    """Create a mock async context manager for tenant.db_session().

    The mock session's execute().scalar_one_or_none() returns query_result.
    """
    mock_session = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = query_result
    mock_session.execute.return_value = mock_exec_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# ── Fixture: create handler with all deps mocked ──


@pytest.fixture()
def handler_env():
    """Create a MessageHandler with all dependencies mocked.

    Patches remain active for the duration of the test so that
    runtime calls to get_redis() etc. hit the mocks.
    """
    mock_session_mgr = AsyncMock()
    mock_sender = AsyncMock()
    mock_media = AsyncMock()
    mock_contact_svc = AsyncMock()
    mock_conv_svc = AsyncMock()
    mock_feedback_svc = AsyncMock()
    mock_redis = AsyncMock()

    patches = (
        patch(
            "app.services.whatsapp.handler.WhatsAppSessionManager", return_value=mock_session_mgr
        ),
        patch("app.services.whatsapp.handler.WhatsAppSenderService", return_value=mock_sender),
        patch("app.services.whatsapp.handler.WhatsAppMediaHandler", return_value=mock_media),
        patch("app.services.whatsapp.handler.get_contact_service", return_value=mock_contact_svc),
        patch("app.services.whatsapp.handler.get_conversation_service", return_value=mock_conv_svc),
        patch("app.services.whatsapp.handler.get_feedback_service", return_value=mock_feedback_svc),
        patch("app.services.whatsapp.handler.get_redis", return_value=mock_redis),
    )

    for p in patches:
        p.start()

    from app.services.whatsapp.handler import MessageHandler

    handler = MessageHandler()

    mocks = {
        "session_mgr": mock_session_mgr,
        "sender": mock_sender,
        "media": mock_media,
        "contact_svc": mock_contact_svc,
        "conv_svc": mock_conv_svc,
        "feedback_svc": mock_feedback_svc,
        "redis": mock_redis,
    }

    yield handler, mocks

    for p in patches:
        p.stop()


def _setup_happy_path(mocks, contact=None, conversation=None, run_result=None):
    """Configure mocks for a standard happy-path flow."""
    contact = contact or _make_mock_contact()
    conversation = conversation or _make_mock_conversation()
    run_result = run_result or _make_run_result()

    mocks["session_mgr"].is_duplicate_message.return_value = False
    mocks["redis"].incr.return_value = 1
    mocks["session_mgr"].check_quota.return_value = _make_quota(is_exhausted=False)
    mocks["contact_svc"].get_or_create.return_value = contact
    mocks["conv_svc"].get_or_create.return_value = conversation
    mocks["conv_svc"].add_message.return_value = _make_mock_message()
    mocks["conv_svc"].get_history.return_value = []
    mocks["sender"].send_text.return_value = "wamid.out123"
    mocks["sender"].mark_as_read.return_value = None

    return contact, conversation, run_result


# ====================================================================
# TEST CASES
# ====================================================================


class TestHappyPath:
    """Full pipeline: text message → LangGraph → response."""

    @pytest.mark.asyncio()
    async def test_happy_path_text_faq(self, handler_env):
        handler, mocks = handler_env
        contact, conversation, run_result = _setup_happy_path(mocks)
        msg = _make_text_message()
        contacts = _make_contacts()

        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=run_result):
            await handler.handle_message(TEST_TENANT, msg, contacts)

        # Dedup checked
        mocks["session_mgr"].is_duplicate_message.assert_awaited_once_with(
            TEST_TENANT,
            TEST_WAMID,
        )
        # Contact created
        mocks["contact_svc"].get_or_create.assert_awaited_once()
        # Conversation created
        mocks["conv_svc"].get_or_create.assert_awaited_once()
        # Inbound + outbound messages persisted
        add_calls = mocks["conv_svc"].add_message.await_args_list
        assert len(add_calls) >= 2
        assert add_calls[0].args[2] == MessageDirection.inbound
        assert add_calls[1].args[2] == MessageDirection.outbound
        # Response sent
        mocks["sender"].send_text.assert_awaited_once()
        # Quota tracked
        mocks["session_mgr"].increment_quota.assert_awaited_once()
        # Metadata updated
        mocks["conv_svc"].update_metadata.assert_awaited_once()


class TestMediaMessages:
    """Image and audio processing via WhatsAppMediaHandler."""

    @pytest.mark.asyncio()
    async def test_image_message_media_processed(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        msg = _make_image_message()

        media_result = MagicMock()
        media_result.success = True
        media_result.extracted_text = "Texte extrait de l'image"
        media_result.minio_path = "cri-rabat/media/2026-03/media_img_123.jpg"
        mocks["media"].process_media.return_value = media_result

        with patch(
            RUN_CONV_PATH,
            new_callable=AsyncMock,
            return_value=_make_run_result(),
        ) as mock_run:
            await handler.handle_message(TEST_TENANT, msg, None)

        mocks["media"].process_media.assert_awaited_once_with(
            TEST_TENANT,
            "media_img_123",
            "image/jpeg",
        )
        # Extracted text + caption used as query
        run_call = mock_run.await_args
        query = run_call.kwargs.get("query", "")
        assert "Texte extrait de l'image" in query
        assert "Mon document" in query

    @pytest.mark.asyncio()
    async def test_audio_message_transcribed(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        msg = _make_audio_message()

        media_result = MagicMock()
        media_result.success = True
        media_result.extracted_text = "Transcription de l'audio"
        media_result.minio_path = "cri-rabat/media/2026-03/media_aud_456.ogg"
        mocks["media"].process_media.return_value = media_result

        with patch(
            RUN_CONV_PATH,
            new_callable=AsyncMock,
            return_value=_make_run_result(),
        ) as mock_run:
            await handler.handle_message(TEST_TENANT, msg, None)

        mocks["media"].process_media.assert_awaited_once_with(
            TEST_TENANT,
            "media_aud_456",
            "audio/ogg",
        )
        run_call = mock_run.await_args
        query = run_call.kwargs.get("query", "")
        assert "Transcription de l'audio" in query


class TestFeedbackRouting:
    """Feedback button clicks routed to FeedbackService."""

    @pytest.mark.asyncio()
    async def test_feedback_positive_routed(self, handler_env):
        handler, mocks = handler_env
        contact = _make_mock_contact()
        conversation = _make_mock_conversation()
        last_outbound = _make_mock_message(direction=MessageDirection.outbound)

        mocks["session_mgr"].is_duplicate_message.return_value = False
        mocks["redis"].incr.return_value = 1
        mocks["session_mgr"].check_quota.return_value = _make_quota()
        mocks["contact_svc"].get_or_create.return_value = contact
        mocks["conv_svc"].get_or_create.return_value = conversation

        msg = _make_feedback_message("feedback_positive")
        mock_session = _make_mock_db_session(query_result=last_outbound)

        with patch.object(TenantContext, "db_session", return_value=mock_session):
            await handler.handle_message(TEST_TENANT, msg, None)

        # Feedback created with correct rating
        mocks["feedback_svc"].create_feedback.assert_awaited_once()
        feedback_data = mocks["feedback_svc"].create_feedback.await_args.args[1]
        assert feedback_data.rating == FeedbackRating.positive
        assert feedback_data.message_id == last_outbound.id

        # Acknowledgment sent
        mocks["sender"].send_text.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_feedback_negative_routed(self, handler_env):
        handler, mocks = handler_env
        contact = _make_mock_contact()
        conversation = _make_mock_conversation()
        last_outbound = _make_mock_message()

        mocks["session_mgr"].is_duplicate_message.return_value = False
        mocks["redis"].incr.return_value = 1
        mocks["session_mgr"].check_quota.return_value = _make_quota()
        mocks["contact_svc"].get_or_create.return_value = contact
        mocks["conv_svc"].get_or_create.return_value = conversation

        msg = _make_feedback_message("feedback_negative")
        mock_session = _make_mock_db_session(query_result=last_outbound)

        with patch.object(TenantContext, "db_session", return_value=mock_session):
            await handler.handle_message(TEST_TENANT, msg, None)

        feedback_data = mocks["feedback_svc"].create_feedback.await_args.args[1]
        assert feedback_data.rating == FeedbackRating.negative


class TestDedup:
    """Message deduplication via Redis."""

    @pytest.mark.asyncio()
    async def test_duplicate_message_skipped(self, handler_env):
        handler, mocks = handler_env
        mocks["session_mgr"].is_duplicate_message.return_value = True

        msg = _make_text_message()
        await handler.handle_message(TEST_TENANT, msg, None)

        mocks["contact_svc"].get_or_create.assert_not_awaited()
        mocks["conv_svc"].get_or_create.assert_not_awaited()
        mocks["sender"].send_text.assert_not_awaited()


class TestRateLimiting:
    """Per-user rate limiting (10 msg/min)."""

    @pytest.mark.asyncio()
    async def test_user_rate_limited(self, handler_env):
        handler, mocks = handler_env
        mocks["session_mgr"].is_duplicate_message.return_value = False
        mocks["redis"].incr.return_value = 11  # Over limit

        msg = _make_text_message()
        await handler.handle_message(TEST_TENANT, msg, None)

        # Rate limit message sent
        mocks["sender"].send_text.assert_awaited_once()
        sent_text = mocks["sender"].send_text.await_args.args[2]
        assert "patienter" in sent_text.lower()

        # No LangGraph execution
        mocks["conv_svc"].get_or_create.assert_not_awaited()


class TestQuota:
    """Tenant message quota enforcement."""

    @pytest.mark.asyncio()
    async def test_quota_exhausted(self, handler_env):
        handler, mocks = handler_env
        mocks["session_mgr"].is_duplicate_message.return_value = False
        mocks["redis"].incr.return_value = 1
        mocks["session_mgr"].check_quota.return_value = _make_quota(is_exhausted=True)

        msg = _make_text_message()
        await handler.handle_message(TEST_TENANT, msg, None)

        mocks["sender"].send_text.assert_awaited_once()
        sent_text = mocks["sender"].send_text.await_args.args[2]
        assert "limite" in sent_text.lower()

        mocks["contact_svc"].get_or_create.assert_not_awaited()


class TestContactManagement:
    """Contact auto-creation from WhatsApp messages."""

    @pytest.mark.asyncio()
    async def test_contact_auto_created_with_name(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        msg = _make_text_message()
        contacts = _make_contacts(name="Fatima Zahra")

        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            await handler.handle_message(TEST_TENANT, msg, contacts)

        call = mocks["contact_svc"].get_or_create.await_args
        assert call.args[1] == TEST_PHONE
        assert call.args[2] == "Fatima Zahra"


class TestConversationLifecycle:
    """Conversation timeout and resumption."""

    @pytest.mark.asyncio()
    async def test_conversation_resumed_within_timeout(self, handler_env):
        handler, mocks = handler_env
        existing_conv = _make_mock_conversation()
        _setup_happy_path(mocks, conversation=existing_conv)
        msg = _make_text_message()

        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            await handler.handle_message(TEST_TENANT, msg, None)

        mocks["conv_svc"].get_or_create.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_conversation_new_after_timeout(self, handler_env):
        """Verify the handler passes correct contact_id to get_or_create."""
        handler, mocks = handler_env
        contact = _make_mock_contact()
        new_conv = _make_mock_conversation()
        _setup_happy_path(mocks, contact=contact, conversation=new_conv)
        msg = _make_text_message()

        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            await handler.handle_message(TEST_TENANT, msg, None)

        call = mocks["conv_svc"].get_or_create.await_args
        assert call.args[1] == contact.id
        assert call.args[2] == AgentType.public


class TestErrorHandling:
    """Graceful error recovery."""

    @pytest.mark.asyncio()
    async def test_langgraph_error_sends_fallback(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        msg = _make_text_message()

        with patch(
            RUN_CONV_PATH,
            new_callable=AsyncMock,
            side_effect=RuntimeError("LangGraph exploded"),
        ):
            await handler.handle_message(TEST_TENANT, msg, None)

        # Error message sent to user
        mocks["sender"].send_text.assert_awaited()
        last_call = mocks["sender"].send_text.await_args
        sent_text = last_call.args[2]
        assert "erreur" in sent_text.lower()


class TestIncentiveState:
    """Incentive state preserved across messages."""

    @pytest.mark.asyncio()
    async def test_incentive_state_preserved(self, handler_env):
        handler, mocks = handler_env
        existing_state = {"current_category_id": "cat_123", "navigation_path": ["root"]}
        conversation = _make_mock_conversation(metadata_={"incentive_state": existing_state})
        _setup_happy_path(mocks, conversation=conversation)

        new_state = {"current_category_id": "cat_456", "navigation_path": ["root", "cat_123"]}
        run_result = _make_run_result(incentive_state=new_state)
        msg = _make_text_message()

        with patch(
            RUN_CONV_PATH,
            new_callable=AsyncMock,
            return_value=run_result,
        ) as mock_run:
            await handler.handle_message(TEST_TENANT, msg, None)

        # Existing incentive_state passed to run_conversation
        run_call = mock_run.await_args
        assert run_call.kwargs.get("incentive_state") == existing_state

        # New incentive_state saved to metadata
        meta_call = mocks["conv_svc"].update_metadata.await_args
        metadata_update = meta_call.args[2]
        assert metadata_update["incentive_state"] == new_state


class TestContactLanguageUpdate:
    """Contact language updated when LangGraph detects a different language."""

    @pytest.mark.asyncio()
    async def test_contact_language_updated(self, handler_env):
        handler, mocks = handler_env
        contact = _make_mock_contact(language=Language.fr)
        _setup_happy_path(mocks, contact=contact)
        run_result = _make_run_result(language="ar")
        msg = _make_text_message()

        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=run_result):
            await handler.handle_message(TEST_TENANT, msg, None)

        mocks["contact_svc"].update_language.assert_awaited_once_with(
            TEST_TENANT,
            contact.id,
            Language.ar,
        )
