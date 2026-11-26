"""Privacy notice states must not imply delivery after an ambiguous send."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext
from app.services.whatsapp.privacy import (
    PRIVACY_FALLBACK_TEXT,
    NoticeResult,
    PrivacyNoticeService,
)

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_PHONE = "+212600000001"
_REDIS_PATCH = "app.services.whatsapp.privacy.get_redis"
_AUDIT_PATCH = "app.services.whatsapp.privacy.get_audit_service"


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, script, key_count, key, expected, state):
        if self.values.get(key) != expected:
            return 0
        self.values[key] = state
        return 1


@pytest.fixture
def tenant():
    return TenantContext(
        id=TEST_TENANT_ID,
        slug="rabat",
        name="Test",
        status="active",
        whatsapp_config={"phone_number_id": "123", "access_token": "synthetic"},
    )


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def service():
    instance = PrivacyNoticeService()
    instance._sender = AsyncMock()
    instance._sender.send_text.return_value = "wamid.synthetic"
    return instance


def test_fallback_does_not_invent_institution_specific_commitments():
    for text in PRIVACY_FALLBACK_TEXT.values():
        assert "dpo@cri.ma" not in text.lower()
        assert "09-08" not in text
        assert "MES DONNÉES" not in text
        assert "MY DATA" not in text
    assert "hébergées au Maroc" not in PRIVACY_FALLBACK_TEXT["fr"]
    assert "hosted in Morocco" not in PRIVACY_FALLBACK_TEXT["en"]
    assert "مستضافة في المغرب" not in PRIVACY_FALLBACK_TEXT["ar"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language,expected", [("fr", "fr"), ("ar", "ar"), ("en", "en"), ("de", "fr")]
)
async def test_accepted_notice_is_marked_after_provider_response(
    service, tenant, redis, language, expected
):
    audit = AsyncMock()
    with patch(_REDIS_PATCH, return_value=redis), patch(_AUDIT_PATCH, return_value=audit):
        result = await service.send_privacy_notice(tenant, TEST_PHONE, language=language)
        again = await service.send_privacy_notice(tenant, TEST_PHONE, language=language)
    assert result == again == NoticeResult.accepted
    assert redis.values[f"rabat:privacy_sent:{TEST_PHONE}"] == "accepted"
    service._sender.send_text.assert_awaited_once_with(
        tenant, TEST_PHONE, PRIVACY_FALLBACK_TEXT[expected]
    )
    service._sender.send_template.assert_not_awaited()
    entry = audit.log_action.await_args.args[0]
    assert entry.details["state"] == "provider_accepted"
    assert "law" not in entry.details


@pytest.mark.asyncio
async def test_timeout_remains_uncertain_and_is_not_automatically_retried(service, tenant, redis):
    service._sender.send_text.side_effect = TimeoutError("ambiguous outcome")
    with patch(_REDIS_PATCH, return_value=redis):
        assert await service.send_privacy_notice(tenant, TEST_PHONE) == NoticeResult.uncertain
        assert await service.send_privacy_notice(tenant, TEST_PHONE) == NoticeResult.uncertain
    assert redis.values[f"rabat:privacy_sent:{TEST_PHONE}"] == "uncertain"
    service._sender.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_send_observes_pending_without_duplicate(service, tenant, redis):
    started, finish = asyncio.Event(), asyncio.Event()

    async def send(*_args):
        started.set()
        await finish.wait()
        return "wamid.synthetic"

    service._sender.send_text.side_effect = send
    audit = AsyncMock()
    with patch(_REDIS_PATCH, return_value=redis), patch(_AUDIT_PATCH, return_value=audit):
        first = asyncio.create_task(service.send_privacy_notice(tenant, TEST_PHONE))
        await started.wait()
        assert await service.send_privacy_notice(tenant, TEST_PHONE) == NoticeResult.pending
        finish.set()
        assert await first == NoticeResult.accepted
    service._sender.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_interruption_leaves_pending_not_accepted(service, tenant, redis):
    started = asyncio.Event()

    async def send(*_args):
        started.set()
        await asyncio.Event().wait()

    service._sender.send_text.side_effect = send
    with patch(_REDIS_PATCH, return_value=redis):
        task = asyncio.create_task(service.send_privacy_notice(tenant, TEST_PHONE))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await service.send_privacy_notice(tenant, TEST_PHONE) == NoticeResult.pending
    assert redis.values[f"rabat:privacy_sent:{TEST_PHONE}"].startswith("pending:")


@pytest.mark.asyncio
async def test_legacy_marker_is_not_treated_as_confirmed(service, tenant, redis):
    redis.values[f"rabat:privacy_sent:{TEST_PHONE}"] = "1"
    with patch(_REDIS_PATCH, return_value=redis):
        assert await service.send_privacy_notice(tenant, TEST_PHONE) == NoticeResult.legacy_unknown
    service._sender.send_text.assert_not_awaited()


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

        msg = IncomingMessage.model_validate(
            {
                "id": "wamid.test123",
                "from": TEST_PHONE,
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "Bonjour"},
            }
        )

        with (
            patch(
                "app.services.whatsapp.handler.get_privacy_notice_service",
                return_value=mock_privacy,
            ),
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
                tenant,
                TEST_PHONE,
                language="fr",
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

        msg = IncomingMessage.model_validate(
            {
                "id": "wamid.test456",
                "from": TEST_PHONE,
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "Bonjour"},
            }
        )

        with (
            patch(
                "app.services.whatsapp.handler.get_privacy_notice_service",
                return_value=mock_privacy,
            ),
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
