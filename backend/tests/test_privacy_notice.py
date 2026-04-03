"""Tests for PrivacyNoticeService — CNDP loi 09-08 Art. 9.

Covers:
- Redis-based idempotency (SET NX)
- Template vs fallback text sending
- Language adaptation (FR/AR/EN)
- Fire-and-forget error handling
- Pipeline integration in MessageHandler
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import WhatsAppSendError
from app.core.tenant import TenantContext
from app.services.whatsapp.privacy import (
    PRIVACY_FALLBACK_TEXT,
    PRIVACY_TEMPLATE_NAME,
    PrivacyNoticeService,
)

# ── Constants ────────────────────────────────────────────────────────────────

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_PHONE = "+212600000001"

_REDIS_PATCH = "app.services.whatsapp.privacy.get_redis"
_AUDIT_PATCH = "app.services.whatsapp.privacy.get_audit_service"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="rabat",
        name="CRI Rabat-Sale-Kenitra",
        status="active",
        whatsapp_config={
            "phone_number_id": "111222333",
            "access_token": "test_access_token",
            "verify_token": "test_verify_token",
            "annual_message_limit": 100_000,
        },
    )


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)  # NX success by default
    return redis


@pytest.fixture
def mock_sender() -> AsyncMock:
    sender = AsyncMock()
    sender.send_template = AsyncMock(return_value="wamid.template123")
    sender.send_text = AsyncMock(return_value="wamid.text456")
    return sender


@pytest.fixture
def mock_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.log_action = AsyncMock()
    return audit


@pytest.fixture
def service(mock_sender: AsyncMock) -> PrivacyNoticeService:
    svc = PrivacyNoticeService()
    svc._sender = mock_sender
    return svc


# ── TestShouldSend ───────────────────────────────────────────────────────────


class TestShouldSend:
    """Tests for the Redis SET NX idempotency check."""

    @pytest.mark.asyncio
    async def test_returns_true_for_new_contact(
        self, service: PrivacyNoticeService, tenant: TenantContext, mock_redis: AsyncMock,
    ) -> None:
        """SET NX returns True → should_send returns True."""
        mock_redis.set = AsyncMock(return_value=True)
        with patch(_REDIS_PATCH, return_value=mock_redis):
            result = await service.should_send(tenant, TEST_PHONE)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_existing_contact(
        self, service: PrivacyNoticeService, tenant: TenantContext, mock_redis: AsyncMock,
    ) -> None:
        """SET NX returns None → should_send returns False."""
        mock_redis.set = AsyncMock(return_value=None)
        with patch(_REDIS_PATCH, return_value=mock_redis):
            result = await service.should_send(tenant, TEST_PHONE)
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_key_format(
        self, service: PrivacyNoticeService, tenant: TenantContext, mock_redis: AsyncMock,
    ) -> None:
        """The Redis key follows the {slug}:privacy_sent:{phone} pattern."""
        with patch(_REDIS_PATCH, return_value=mock_redis):
            await service.should_send(tenant, TEST_PHONE)
        mock_redis.set.assert_awaited_once_with(
            f"rabat:privacy_sent:{TEST_PHONE}",
            "1",
            nx=True,
        )

    @pytest.mark.asyncio
    async def test_no_ttl_on_key(
        self, service: PrivacyNoticeService, tenant: TenantContext, mock_redis: AsyncMock,
    ) -> None:
        """The key has no TTL — privacy notice is permanent."""
        with patch(_REDIS_PATCH, return_value=mock_redis):
            await service.should_send(tenant, TEST_PHONE)
        call_kwargs = mock_redis.set.call_args
        # No `ex` or `px` argument should be passed
        assert "ex" not in (call_kwargs.kwargs if call_kwargs.kwargs else {})
        assert "px" not in (call_kwargs.kwargs if call_kwargs.kwargs else {})


# ── TestSendPrivacyNotice ────────────────────────────────────────────────────


class TestSendPrivacyNotice:
    """Tests for the send_privacy_notice fire-and-forget method."""

    @pytest.mark.asyncio
    async def test_template_success(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """When template succeeds, send_template is called and audit logs method=template."""
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="fr")

        mock_sender.send_template.assert_awaited_once_with(
            tenant, TEST_PHONE, PRIVACY_TEMPLATE_NAME, "fr",
        )
        mock_sender.send_text.assert_not_awaited()

        # Check audit log
        audit_call = mock_audit.log_action.call_args[0][0]
        assert audit_call.action == "privacy_notice"
        assert audit_call.details["method"] == "template"
        assert audit_call.details["language"] == "fr"

    @pytest.mark.asyncio
    async def test_template_fails_fallback_to_text(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """When template fails, fallback to send_text with localized text."""
        mock_sender.send_template = AsyncMock(
            side_effect=WhatsAppSendError("Template not approved"),
        )
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="fr")

        mock_sender.send_text.assert_awaited_once_with(
            tenant, TEST_PHONE, PRIVACY_FALLBACK_TEXT["fr"],
        )

        audit_call = mock_audit.log_action.call_args[0][0]
        assert audit_call.details["method"] == "text"

    @pytest.mark.asyncio
    async def test_already_sent_skips(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
    ) -> None:
        """When should_send returns False, no message is sent."""
        mock_redis.set = AsyncMock(return_value=None)  # Already sent
        with patch(_REDIS_PATCH, return_value=mock_redis):
            await service.send_privacy_notice(tenant, TEST_PHONE)

        mock_sender.send_template.assert_not_awaited()
        mock_sender.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_arabic_language(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """Arabic language uses ar template and Arabic fallback text."""
        mock_sender.send_template = AsyncMock(
            side_effect=WhatsAppSendError("no template"),
        )
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="ar")

        mock_sender.send_text.assert_awaited_once_with(
            tenant, TEST_PHONE, PRIVACY_FALLBACK_TEXT["ar"],
        )

    @pytest.mark.asyncio
    async def test_english_language(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """English language uses en template and English fallback text."""
        mock_sender.send_template = AsyncMock(
            side_effect=WhatsAppSendError("no template"),
        )
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="en")

        mock_sender.send_text.assert_awaited_once_with(
            tenant, TEST_PHONE, PRIVACY_FALLBACK_TEXT["en"],
        )

    @pytest.mark.asyncio
    async def test_unknown_language_falls_back_to_french(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """Unknown language code falls back to French text."""
        mock_sender.send_template = AsyncMock(
            side_effect=WhatsAppSendError("no template"),
        )
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="de")

        mock_sender.send_text.assert_awaited_once_with(
            tenant, TEST_PHONE, PRIVACY_FALLBACK_TEXT["fr"],
        )

    @pytest.mark.asyncio
    async def test_total_failure_swallowed(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
    ) -> None:
        """If both template and text fail, no exception propagates."""
        mock_sender.send_template = AsyncMock(
            side_effect=WhatsAppSendError("template fail"),
        )
        mock_sender.send_text = AsyncMock(
            side_effect=RuntimeError("text also fails"),
        )
        with patch(_REDIS_PATCH, return_value=mock_redis):
            # Must NOT raise
            await service.send_privacy_notice(tenant, TEST_PHONE)

    @pytest.mark.asyncio
    async def test_audit_log_fields(
        self,
        service: PrivacyNoticeService,
        tenant: TenantContext,
        mock_redis: AsyncMock,
        mock_sender: AsyncMock,
        mock_audit: AsyncMock,
    ) -> None:
        """Audit log contains all required CNDP fields."""
        with (
            patch(_REDIS_PATCH, return_value=mock_redis),
            patch(_AUDIT_PATCH, return_value=mock_audit),
        ):
            await service.send_privacy_notice(tenant, TEST_PHONE, language="fr")

        mock_audit.log_action.assert_awaited_once()
        data = mock_audit.log_action.call_args[0][0]
        assert data.tenant_slug == "rabat"
        assert data.user_type == "system"
        assert data.action == "privacy_notice"
        assert data.resource_type == "contact"
        assert data.resource_id == TEST_PHONE
        assert data.details["law"] == "09-08"
        assert data.details["article"] == "9"


# ── TestPipelineIntegration ──────────────────────────────────────────────────


class TestPipelineIntegration:
    """Tests that the privacy notice integrates correctly in MessageHandler."""

    @pytest.mark.asyncio
    async def test_privacy_service_called_in_handler(self, tenant: TenantContext) -> None:
        """MessageHandler calls send_privacy_notice between steps 4 and 5."""
        from app.schemas.whatsapp import IncomingMessage

        mock_privacy = AsyncMock()
        mock_privacy.send_privacy_notice = AsyncMock()

        mock_contact = MagicMock()
        mock_contact.id = uuid.uuid4()
        mock_contact.language = MagicMock()
        mock_contact.language.value = "fr"

        msg = IncomingMessage.model_validate({
            "id": "wamid.test123",
            "from": TEST_PHONE,
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "Bonjour"},
        })

        with (
            patch("app.services.whatsapp.handler.get_privacy_notice_service", return_value=mock_privacy),
            patch("app.services.whatsapp.handler.get_contact_service") as mock_cs,
            patch("app.services.whatsapp.handler.get_conversation_service") as mock_conv,
            patch("app.services.whatsapp.handler.get_feedback_service"),
            patch("app.services.whatsapp.handler.get_segmentation_service"),
            patch("app.services.whatsapp.handler.get_redis") as mock_redis_fn,
        ):
            mock_redis_inst = AsyncMock()
            mock_redis_inst.set = AsyncMock(return_value=None)  # dedup: not duplicate
            mock_redis_inst.incr = AsyncMock(return_value=1)
            mock_redis_inst.expire = AsyncMock()
            mock_redis_fn.return_value = mock_redis_inst

            mock_cs_inst = AsyncMock()
            mock_cs_inst.get_or_create = AsyncMock(return_value=mock_contact)
            mock_cs.return_value = mock_cs_inst

            mock_conv_inst = AsyncMock()
            mock_conv_inst.get_or_create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            mock_conv.return_value = mock_conv_inst

            # Import after patching singletons
            from app.services.whatsapp.handler import MessageHandler

            handler = MessageHandler()
            # Override internal services to avoid unpatched calls
            handler._session_manager = AsyncMock()
            handler._session_manager.is_duplicate_message = AsyncMock(return_value=False)
            handler._session_manager.check_quota = AsyncMock(
                return_value=MagicMock(is_exhausted=False),
            )
            handler._session_manager.get_or_create_session = AsyncMock(
                return_value=MagicMock(is_active=True),
            )
            handler._session_manager.increment_quota = AsyncMock()
            handler._sender = AsyncMock()
            handler._sender.send_text = AsyncMock(return_value="wamid.resp")
            handler._sender.send_buttons = AsyncMock(return_value="wamid.btn")
            handler._sender.mark_as_read = AsyncMock()
            handler._media_handler = AsyncMock()
            handler._contact_service = mock_cs_inst
            handler._conversation_service = mock_conv_inst

            # Mock LangGraph orchestrator (lazy import inside handler)
            with patch("app.services.orchestrator.graph.run_conversation") as mock_run:
                mock_run.return_value = {
                    "response": "Bienvenue",
                    "intent": "faq",
                    "language": "fr",
                    "confidence": 0.95,
                    "chunk_ids": [],
                }
                try:
                    await handler.handle_message(tenant, msg, None)
                except Exception:
                    pass  # Pipeline may fail on downstream mocks; we only check privacy

            mock_privacy.send_privacy_notice.assert_awaited_once_with(
                tenant, TEST_PHONE, language="fr",
            )

    @pytest.mark.asyncio
    async def test_privacy_failure_does_not_block_pipeline(self, tenant: TenantContext) -> None:
        """If send_privacy_notice raises, the pipeline continues normally."""
        from app.schemas.whatsapp import IncomingMessage

        mock_privacy = AsyncMock()
        mock_privacy.send_privacy_notice = AsyncMock(
            side_effect=RuntimeError("Privacy service exploded"),
        )

        mock_contact = MagicMock()
        mock_contact.id = uuid.uuid4()
        mock_contact.language = MagicMock()
        mock_contact.language.value = "fr"

        msg = IncomingMessage.model_validate({
            "id": "wamid.test456",
            "from": TEST_PHONE,
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "Bonjour"},
        })

        with (
            patch("app.services.whatsapp.handler.get_privacy_notice_service", return_value=mock_privacy),
            patch("app.services.whatsapp.handler.get_contact_service") as mock_cs,
            patch("app.services.whatsapp.handler.get_conversation_service") as mock_conv,
            patch("app.services.whatsapp.handler.get_feedback_service"),
            patch("app.services.whatsapp.handler.get_segmentation_service"),
            patch("app.services.whatsapp.handler.get_redis") as mock_redis_fn,
        ):
            mock_redis_inst = AsyncMock()
            mock_redis_inst.set = AsyncMock(return_value=None)
            mock_redis_inst.incr = AsyncMock(return_value=1)
            mock_redis_inst.expire = AsyncMock()
            mock_redis_fn.return_value = mock_redis_inst

            mock_cs_inst = AsyncMock()
            mock_cs_inst.get_or_create = AsyncMock(return_value=mock_contact)
            mock_cs.return_value = mock_cs_inst

            mock_conv_inst = AsyncMock()
            mock_conv_inst.get_or_create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            mock_conv.return_value = mock_conv_inst

            from app.services.whatsapp.handler import MessageHandler

            handler = MessageHandler()
            handler._session_manager = AsyncMock()
            handler._session_manager.is_duplicate_message = AsyncMock(return_value=False)
            handler._session_manager.check_quota = AsyncMock(
                return_value=MagicMock(is_exhausted=False),
            )
            handler._session_manager.get_or_create_session = AsyncMock(
                return_value=MagicMock(is_active=True),
            )
            handler._session_manager.increment_quota = AsyncMock()
            handler._sender = AsyncMock()
            handler._sender.send_text = AsyncMock(return_value="wamid.resp")
            handler._sender.send_buttons = AsyncMock(return_value="wamid.btn")
            handler._sender.mark_as_read = AsyncMock()
            handler._media_handler = AsyncMock()
            handler._contact_service = mock_cs_inst
            handler._conversation_service = mock_conv_inst

            with patch("app.services.orchestrator.graph.run_conversation") as mock_run:
                mock_run.return_value = {
                    "response": "Bienvenue",
                    "intent": "faq",
                    "language": "fr",
                    "confidence": 0.95,
                    "chunk_ids": [],
                }
                try:
                    await handler.handle_message(tenant, msg, None)
                except Exception:
                    pass

            # Despite privacy service raising, conversation was still created
            mock_conv_inst.get_or_create.assert_awaited_once()
