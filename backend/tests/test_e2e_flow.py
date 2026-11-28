"""End-to-end tests for the WhatsApp → LangGraph → Response pipeline.

Tests cover the full MessageHandler flow: dedup, rate limiting, quota,
contact/conversation management, media processing, feedback routing,
LangGraph execution, message persistence, and error handling.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.models.enums import (
    AgentType,
    ConversationStatus,
    FeedbackRating,
    Language,
    MessageDirection,
    OptInStatus,
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


@asynccontextmanager
async def _allow_reply(*_args):
    yield True


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
    mock_conv_svc.guard_bot_reply = MagicMock(side_effect=_allow_reply)
    mock_feedback_svc = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 1

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
    mocks["redis"].eval.return_value = 1
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
    @pytest.mark.parametrize("notice,expected", [("accepted", "suppressed"), ("uncertain", "uncertain")])
    async def test_suppressed_response_never_records_a_fake_outbound(self, handler_env, notice, expected):
        from app.services.whatsapp.outbound_fence import OutboundSupersededError
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult(notice)
        mocks["sender"].send_text.side_effect = OutboundSupersededError("stopped")
        tracking = AsyncMock()
        tracking.get_state.return_value = MagicMock(step=MagicMock(value="idle"))
        with (
            patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()),
            patch("app.services.orchestrator.tracking_state.TrackingStateManager", return_value=tracking),
        ):
            outcome = await handler.handle_message(TEST_TENANT, _make_text_message(), None, durable=True)
        assert outcome.value == expected
        assert all(call.args[2] != MessageDirection.outbound for call in mocks["conv_svc"].add_message.await_args_list)
        mocks["session_mgr"].increment_quota.assert_not_awaited()
    @pytest.mark.asyncio()
    async def test_takeover_before_privacy_notice_keeps_inbound_and_suppresses_bot(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["conv_svc"].get_status.return_value = ConversationStatus.active

        @asynccontextmanager
        async def deny_reply(*_args):
            yield False

        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        handler._privacy_service = AsyncMock()
        with patch(RUN_CONV_PATH, new_callable=AsyncMock) as run:
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        mocks["conv_svc"].add_message.assert_awaited_once()
        mocks["redis"].publish.assert_awaited_once()
        handler._privacy_service.send_privacy_notice.assert_not_awaited()
        mocks["sender"].send_text.assert_not_awaited()
        run.assert_not_awaited()

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("status", [ConversationStatus.escalated, ConversationStatus.human_handled])
    async def test_open_handoff_persists_inbound_without_bot_reply(self, handler_env, status):
        handler, mocks = handler_env
        _, conversation, _ = _setup_happy_path(mocks)
        mocks["conv_svc"].get_status.return_value = status

        with patch(RUN_CONV_PATH, new_callable=AsyncMock) as run:
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)

        assert mocks["conv_svc"].get_or_create.await_args.kwargs["resume_escalated"] is True
        assert mocks["conv_svc"].add_message.await_count == 1
        assert mocks["conv_svc"].add_message.await_args.args[2] == MessageDirection.inbound
        run.assert_not_awaited()
        mocks["sender"].send_text.assert_not_awaited()
        mocks["redis"].publish.assert_awaited_once()
        assert str(conversation.id) in mocks["redis"].publish.await_args.args[1]

    @pytest.mark.asyncio()
    async def test_takeover_during_generation_suppresses_bot_response(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["conv_svc"].get_status.return_value = ConversationStatus.active
        calls = 0
        @asynccontextmanager
        async def deny_reply(*_args):
            nonlocal calls
            calls += 1
            yield calls == 1
        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        assert mocks["conv_svc"].add_message.await_count == 1
        mocks["sender"].send_text.assert_not_awaited()
        mocks["redis"].publish.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_feedback_is_sent_only_after_the_answer(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        observed = []
        async def send_text(*_args):
            observed.append("answer")
            return "wamid.reply"
        async def send_buttons(*_args):
            observed.append("feedback")
            return "wamid.feedback"
        mocks["sender"].send_text.side_effect = send_text
        mocks["sender"].send_buttons.side_effect = send_buttons
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()) as run:
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        assert run.await_args.kwargs["defer_feedback"] is True
        assert run.await_args.kwargs["tracking_available"] is False
        assert observed == ["answer", "feedback"]

    @pytest.mark.asyncio()
    async def test_unavailable_send_guard_never_sends_an_unfenced_reply(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        @asynccontextmanager
        async def fail_guard(*_args):
            raise TimeoutError("fixture lock unavailable")
            yield  # pragma: no cover
        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=fail_guard)
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            outcome = await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        assert outcome.value == "uncertain"
        mocks["sender"].send_text.assert_not_awaited()
        assert mocks["conv_svc"].add_message.await_args_list[-1].kwargs["metadata"]["delivery_state"] == "unconfirmed"

    @pytest.mark.asyncio()
    async def test_new_escalation_transition_is_not_suppressed(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["conv_svc"].get_status.return_value = ConversationStatus.active
        result = _make_run_result(escalation_id=str(uuid.uuid4()), response="Demande enregistrée")
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=result):
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        mocks["sender"].send_text.assert_awaited_once()

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

    @pytest.mark.asyncio()
    async def test_failed_send_is_recorded_as_unconfirmed(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["sender"].send_text.side_effect = TimeoutError("provider timeout")
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)

        outbound = mocks["conv_svc"].add_message.await_args_list[1]
        assert outbound.kwargs["metadata"]["delivery_state"] == "unconfirmed"
        assert outbound.kwargs["whatsapp_message_id"] is None
        mocks["session_mgr"].increment_quota.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_durable_mode_reports_provider_acceptance_and_skips_redis_dedup(
        self, handler_env
    ):
        from app.services.whatsapp.handler import HandlingOutcome
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.accepted
        tracking = AsyncMock()
        tracking.get_state.return_value = MagicMock(step=MagicMock(value="idle"))
        with (
            patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()),
            patch(
                "app.services.orchestrator.tracking_state.TrackingStateManager",
                return_value=tracking,
            ),
        ):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_text_message(), None, durable=True
            )
        assert outcome == HandlingOutcome.accepted
        mocks["session_mgr"].is_duplicate_message.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_durable_failure_never_sends_an_extra_error_response(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.accepted
        mocks["sender"].send_text.side_effect = TimeoutError("ambiguous outcome")
        with patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_text_message(), None, durable=True
            )
        assert outcome == HandlingOutcome.uncertain
        mocks["sender"].send_text.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_durable_failure_before_response_does_not_send_fallback(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["contact_svc"].get_or_create.side_effect = RuntimeError("db unavailable")
        outcome = await handler.handle_message(
            TEST_TENANT, _make_text_message(), None, durable=True
        )
        assert outcome == HandlingOutcome.uncertain
        mocks["sender"].send_text.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_durable_pending_privacy_notice_requires_review(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.pending
        tracking = AsyncMock()
        tracking.get_state.return_value = MagicMock(step=MagicMock(value="idle"))
        with (
            patch(RUN_CONV_PATH, new_callable=AsyncMock, return_value=_make_run_result()),
            patch(
                "app.services.orchestrator.tracking_state.TrackingStateManager",
                return_value=tracking,
            ),
        ):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_text_message(), None, durable=True
            )
        assert outcome == HandlingOutcome.uncertain

    @pytest.mark.asyncio()
    async def test_durable_stop_with_unconfirmed_opt_out_is_uncertain(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.accepted
        segmentation = AsyncMock()
        segmentation.process_stop_command.return_value = False
        with patch(
            "app.services.whatsapp.handler.get_segmentation_service", return_value=segmentation
        ):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_text_message(body="STOP"), None, durable=True
            )
        assert outcome == HandlingOutcome.uncertain
        mocks["sender"].send_text.assert_not_awaited()


class TestStopPriority:
    @pytest.mark.asyncio()
    async def test_stop_already_recorded_at_intake_can_be_acknowledged(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome

        handler, mocks = handler_env
        contact, _, _ = _setup_happy_path(mocks)
        contact.opt_in_status = OptInStatus.opted_out
        segmentation = AsyncMock()
        segmentation.process_stop_command.return_value = False
        with patch("app.services.whatsapp.handler.get_segmentation_service", return_value=segmentation):
            outcome = await handler.handle_message(TEST_TENANT, _make_text_message(body="STOP"), None, durable=True)
        assert outcome == HandlingOutcome.accepted
        mocks["sender"].send_text.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_stop_bypasses_dedup_rate_quota_and_privacy_notice(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["session_mgr"].is_duplicate_message.side_effect = RuntimeError("redis down")
        mocks["session_mgr"].check_quota.return_value = _make_quota(is_exhausted=True)
        handler._privacy_service = AsyncMock()
        segmentation = AsyncMock()
        segmentation.process_stop_command.return_value = True
        with patch(
            "app.services.whatsapp.handler.get_segmentation_service", return_value=segmentation
        ):
            await handler.handle_message(TEST_TENANT, _make_text_message(body=" STOP "), None)
        segmentation.process_stop_command.assert_awaited_once_with(TEST_TENANT, TEST_PHONE)
        mocks["session_mgr"].is_duplicate_message.assert_not_awaited()
        mocks["session_mgr"].check_quota.assert_not_awaited()
        handler._privacy_service.send_privacy_notice.assert_not_awaited()
        mocks["conv_svc"].get_or_create.assert_not_awaited()
        mocks["sender"].send_text.assert_awaited_once()
        assert "enregistrée" in mocks["sender"].send_text.await_args.args[2]

    @pytest.mark.asyncio()
    async def test_stop_database_failure_never_confirms_unsubscribe(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        segmentation = AsyncMock()
        segmentation.process_stop_command.side_effect = RuntimeError("db down")
        with patch(
            "app.services.whatsapp.handler.get_segmentation_service", return_value=segmentation
        ):
            await handler.handle_message(TEST_TENANT, _make_text_message(body="STOP"), None)
        mocks["sender"].send_text.assert_not_awaited()


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
    @pytest.mark.parametrize(
        ("record_fails", "ack", "expected"),
        [(False, "wamid.ack", "accepted"), (True, "wamid.ack", "uncertain"),
         (False, None, "uncertain")],
    )
    async def test_durable_feedback_requires_record_and_provider_acceptance(
        self, handler_env, record_fails, ack, expected
    ):
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.accepted
        mocks["sender"].send_text.return_value = ack
        if record_fails:
            mocks["feedback_svc"].create_feedback.side_effect = RuntimeError("db failed")
        session = _make_mock_db_session(query_result=_make_mock_message())
        with patch.object(TenantContext, "db_session", return_value=session):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_feedback_message(), None, durable=True
            )
        assert outcome.value == expected
        mocks["sender"].send_text.assert_awaited_once()

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("ack,expected", [("wamid.source", "accepted"), (None, "uncertain")])
    async def test_durable_source_requires_provider_acceptance(self, handler_env, ack, expected):
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.accepted
        mocks["sender"].send_text.return_value = ack
        mocks["conv_svc"].get_latest_sources.return_value = []
        outcome = await handler.handle_message(
            TEST_TENANT, _make_text_message(body="source"), None, durable=True
        )
        assert outcome.value == expected
        assert mocks["conv_svc"].add_message.await_count == 2
        mocks["sender"].send_text.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_durable_feedback_with_pending_privacy_notice_requires_review(self, handler_env):
        from app.services.whatsapp.privacy import NoticeResult

        handler, mocks = handler_env
        _setup_happy_path(mocks)
        handler._privacy_service = AsyncMock()
        handler._privacy_service.send_privacy_notice.return_value = NoticeResult.pending
        session = _make_mock_db_session(query_result=_make_mock_message())
        with patch.object(TenantContext, "db_session", return_value=session):
            outcome = await handler.handle_message(
                TEST_TENANT, _make_feedback_message(), None, durable=True
            )
        assert outcome.value == "uncertain"

    @pytest.mark.asyncio()
    async def test_human_takeover_suppresses_source_reply(self, handler_env):
        handler, mocks = handler_env
        _, conversation, _ = _setup_happy_path(mocks)
        calls = 0
        @asynccontextmanager
        async def deny_reply(*_args):
            nonlocal calls
            calls += 1
            yield calls == 1
        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        mocks["conv_svc"].get_latest_sources.return_value = []
        await handler.handle_message(TEST_TENANT, _make_text_message("source"), None)
        assert mocks["conv_svc"].add_message.await_count == 1
        mocks["sender"].send_text.assert_not_awaited()
        mocks["redis"].publish.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_human_takeover_suppresses_feedback_ack(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        @asynccontextmanager
        async def deny_reply(*_args):
            yield False
        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        session = _make_mock_db_session(query_result=_make_mock_message())
        with patch.object(TenantContext, "db_session", return_value=session):
            await handler._handle_feedback(TEST_TENANT, _make_feedback_message(), uuid.uuid4(), TEST_PHONE)
        mocks["feedback_svc"].create_feedback.assert_awaited_once()
        mocks["sender"].send_text.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_feedback_positive_routed(self, handler_env):
        handler, mocks = handler_env
        contact = _make_mock_contact()
        conversation = _make_mock_conversation()
        last_outbound = _make_mock_message(direction=MessageDirection.outbound)

        mocks["session_mgr"].is_duplicate_message.return_value = False
        mocks["redis"].eval.return_value = 1
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
        mocks["redis"].eval.return_value = 1
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
    async def test_durable_rate_limit_defers_before_external_side_effects(self, handler_env):
        from app.services.whatsapp.handler import HandlingOutcome

        handler, mocks = handler_env
        mocks["redis"].eval.return_value = 11
        handler._privacy_service = AsyncMock()
        outcome = await handler.handle_message(TEST_TENANT, _make_text_message(), None, durable=True)
        assert outcome == HandlingOutcome.deferred
        mocks["session_mgr"].is_duplicate_message.assert_not_awaited()
        mocks["contact_svc"].get_or_create.assert_not_awaited()
        mocks["conv_svc"].add_message.assert_not_awaited()
        mocks["sender"].send_text.assert_not_awaited()
        handler._privacy_service.send_privacy_notice.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_user_rate_limited(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["redis"].eval.return_value = 11  # Over limit

        msg = _make_text_message()
        await handler.handle_message(TEST_TENANT, msg, None)

        # Rate limit message sent
        mocks["sender"].send_text.assert_awaited_once()
        sent_text = mocks["sender"].send_text.await_args.args[2]
        assert "patienter" in sent_text.lower()

        # Rate-limit notices are serialized with human takeover.
        mocks["conv_svc"].guard_bot_reply.assert_called_once()
        mocks["conv_svc"].add_message.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_rate_limited_handoff_persists_without_automatic_message(self, handler_env):
        handler, mocks = handler_env
        _, conversation, _ = _setup_happy_path(mocks)
        mocks["redis"].eval.side_effect = [11, 1]
        mocks["conv_svc"].get_status.return_value = ConversationStatus.human_handled

        @asynccontextmanager
        async def deny_reply(*_args):
            yield False

        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        handler._privacy_service = AsyncMock()
        with patch(RUN_CONV_PATH, new_callable=AsyncMock) as run:
            await handler.handle_message(TEST_TENANT, _make_text_message(), None)
        mocks["conv_svc"].add_message.assert_awaited_once()
        assert mocks["conv_svc"].add_message.await_args.args[1] == conversation.id
        mocks["sender"].send_text.assert_not_awaited()
        handler._privacy_service.send_privacy_notice.assert_not_awaited()
        mocks["redis"].publish.assert_awaited_once()
        run.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_handoff_extra_allowance_is_bounded(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["redis"].eval.side_effect = [11, 21]

        @asynccontextmanager
        async def deny_reply(*_args):
            yield False

        mocks["conv_svc"].guard_bot_reply = MagicMock(side_effect=deny_reply)
        from app.services.whatsapp.handler import HandlingOutcome

        assert await handler.handle_message(TEST_TENANT, _make_text_message(), None) == HandlingOutcome.uncertain
        mocks["conv_svc"].add_message.assert_not_awaited()
        mocks["sender"].send_text.assert_not_awaited()


class TestQuota:
    """Tenant message quota enforcement."""

    @pytest.mark.asyncio()
    async def test_quota_exhausted(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["session_mgr"].check_quota.return_value = _make_quota(is_exhausted=True)

        msg = _make_text_message()
        await handler.handle_message(TEST_TENANT, msg, None)

        mocks["sender"].send_text.assert_awaited_once()
        sent_text = mocks["sender"].send_text.await_args.args[2]
        assert "limite" in sent_text.lower()

        mocks["contact_svc"].get_or_create.assert_awaited_once()
        assert mocks["conv_svc"].add_message.await_count == 1

    @pytest.mark.asyncio()
    async def test_bot_quota_does_not_drop_message_for_human_handoff(self, handler_env):
        handler, mocks = handler_env
        _setup_happy_path(mocks)
        mocks["session_mgr"].check_quota.return_value = _make_quota(is_exhausted=True)
        mocks["conv_svc"].get_status.return_value = ConversationStatus.human_handled

        await handler.handle_message(TEST_TENANT, _make_text_message(), None)

        mocks["session_mgr"].check_quota.assert_not_awaited()
        assert mocks["conv_svc"].add_message.await_count == 1
        mocks["sender"].send_text.assert_not_awaited()
        mocks["redis"].publish.assert_awaited_once()


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
