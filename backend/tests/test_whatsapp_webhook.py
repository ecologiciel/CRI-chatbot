"""Tests for WhatsApp webhook endpoints and service.

Covers: GET verification, POST HMAC validation, deduplication, rate limiting.
"""

import hashlib
import hmac
import json
import os
import uuid
from unittest.mock import AsyncMock, patch

# Set required env vars BEFORE importing app (which triggers Settings())
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("REDIS_PASSWORD", "test_password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test_password")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test_app_secret_123")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify_token_456")

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.tenant import TenantContext
from app.main import app
from app.services.whatsapp.webhook import WhatsAppWebhookService


# --- Fixtures ---

TEST_TENANT_ID = uuid.uuid4()
TEST_APP_SECRET = "test_app_secret_123"
TEST_VERIFY_TOKEN = "test_verify_token_456"
TEST_PHONE_NUMBER_ID = "111222333"


def _make_tenant_context(**overrides) -> TenantContext:
    defaults = {
        "id": TEST_TENANT_ID,
        "slug": "rabat",
        "name": "CRI Rabat-Salé-Kénitra",
        "status": "active",
        "whatsapp_config": {
            "phone_number_id": TEST_PHONE_NUMBER_ID,
            "access_token": "test_token",
            "verify_token": TEST_VERIFY_TOKEN,
        },
    }
    defaults.update(overrides)
    return TenantContext(**defaults)


def _make_webhook_payload(wamid: str = "wamid.test123") -> dict:
    """Build a minimal valid Meta webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "BIZ_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+212600000000",
                                "phone_number_id": TEST_PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": "212600000001",
                                }
                            ],
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": "212600000001",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "Bonjour"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _sign_payload(payload_bytes: bytes, secret: str = TEST_APP_SECRET) -> str:
    """Compute HMAC-SHA256 signature in Meta's format."""
    digest = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _mock_settings():
    """Create a mock settings object with WhatsApp config."""
    mock = AsyncMock()
    mock.whatsapp_app_secret = TEST_APP_SECRET
    mock.whatsapp_verify_token = TEST_VERIFY_TOKEN
    return mock


# --- GET Verification Tests ---


class TestWebhookVerification:
    @pytest.mark.asyncio
    async def test_verify_success(self):
        """GET with correct mode/token returns 200 + challenge."""
        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/webhook/whatsapp",
                    params={
                        "hub.mode": "subscribe",
                        "hub.verify_token": TEST_VERIFY_TOKEN,
                        "hub.challenge": "challenge_string_123",
                    },
                )

        assert response.status_code == 200
        assert response.text == "challenge_string_123"

    @pytest.mark.asyncio
    async def test_verify_wrong_token(self):
        """GET with wrong verify_token returns 403."""
        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/webhook/whatsapp",
                    params={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "wrong_token",
                        "hub.challenge": "challenge_string_123",
                    },
                )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_verify_wrong_mode(self):
        """GET with mode != 'subscribe' returns 403."""
        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/webhook/whatsapp",
                    params={
                        "hub.mode": "unsubscribe",
                        "hub.verify_token": TEST_VERIFY_TOKEN,
                        "hub.challenge": "challenge_string_123",
                    },
                )

        assert response.status_code == 403


# --- POST Webhook Tests ---


class TestWebhookPost:
    @pytest.mark.asyncio
    async def test_valid_hmac(self):
        """POST with valid HMAC signature returns 200."""
        payload = _make_webhook_payload()
        body = json.dumps(payload).encode()
        signature = _sign_payload(body)
        tenant = _make_tenant_context()

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX: new message
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with (
            patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()),
            patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis),
            patch(
                "app.services.whatsapp.webhook.TenantResolver.from_phone_number_id",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": signature,
                        "Content-Type": "application/json",
                    },
                )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_invalid_hmac(self):
        """POST with wrong HMAC signature returns 403."""
        payload = _make_webhook_payload()
        body = json.dumps(payload).encode()

        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": "sha256=invalid_signature",
                        "Content-Type": "application/json",
                    },
                )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_signature(self):
        """POST without X-Hub-Signature-256 header returns 403."""
        payload = _make_webhook_payload()
        body = json.dumps(payload).encode()

        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 403


# --- Deduplication Tests ---


class TestWebhookDedup:
    @pytest.mark.asyncio
    async def test_duplicate_skipped(self):
        """Same wamid sent twice — second call is silently skipped."""
        payload = _make_webhook_payload(wamid="wamid.dupe_test")
        body = json.dumps(payload).encode()
        signature = _sign_payload(body)
        tenant = _make_tenant_context()

        call_count = 0

        async def mock_set(key, value, ex=None, nx=False):
            nonlocal call_count
            call_count += 1
            # First call: new message (True), Second call: duplicate (None/False)
            return call_count == 1

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=mock_set)
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with (
            patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()),
            patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis),
            patch(
                "app.services.whatsapp.webhook.TenantResolver.from_phone_number_id",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # First request — should process
                resp1 = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": signature,
                        "Content-Type": "application/json",
                    },
                )
                # Second request — should be deduplicated
                resp2 = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": signature,
                        "Content-Type": "application/json",
                    },
                )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Redis SET was called twice (once per request) — first returned True, second False
        assert call_count == 2


# --- Rate Limiting Tests ---


class TestWebhookRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        """When INCR returns > 50, rate limit is exceeded but 200 is still returned."""
        payload = _make_webhook_payload()
        body = json.dumps(payload).encode()
        signature = _sign_payload(body)
        tenant = _make_tenant_context()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=51)  # Over limit
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with (
            patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()),
            patch("app.services.whatsapp.webhook.get_redis", return_value=mock_redis),
            patch(
                "app.services.whatsapp.webhook.TenantResolver.from_phone_number_id",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": signature,
                        "Content-Type": "application/json",
                    },
                )

        # Returns 200 to Meta even on rate limit (error is logged, not exposed)
        assert response.status_code == 200


# --- HMAC Validation Unit Tests ---


class TestHmacValidation:
    def test_validate_hmac_signature_correct(self):
        """Valid HMAC signature should not raise."""
        body = b'{"test": "data"}'
        signature = _sign_payload(body)

        with patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()):
            # Should not raise
            WhatsAppWebhookService._validate_hmac_signature(body, signature)

    def test_validate_hmac_signature_incorrect(self):
        """Invalid HMAC signature should raise WhatsAppSignatureError."""
        from app.core.exceptions import WhatsAppSignatureError

        body = b'{"test": "data"}'

        with (
            patch("app.services.whatsapp.webhook.get_settings", return_value=_mock_settings()),
            pytest.raises(WhatsAppSignatureError),
        ):
            WhatsAppWebhookService._validate_hmac_signature(body, "sha256=wrong")

    def test_validate_hmac_signature_missing(self):
        """Missing signature should raise WhatsAppSignatureError."""
        from app.core.exceptions import WhatsAppSignatureError

        body = b'{"test": "data"}'

        with pytest.raises(WhatsAppSignatureError):
            WhatsAppWebhookService._validate_hmac_signature(body, None)
