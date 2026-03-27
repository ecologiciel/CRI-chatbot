"""HMAC webhook security edge-case tests.

Supplements test_whatsapp_webhook.py with additional security scenarios:
body tampering, wrong algorithm prefix, constant-time comparison, etc.
"""

import hashlib
import hmac as hmac_mod
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.whatsapp.webhook import WhatsAppWebhookService

TEST_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "test_app_secret_123")
TEST_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "test_verify_token_456")


def _sign(payload: bytes, secret: str = TEST_APP_SECRET) -> str:
    """Compute HMAC-SHA256 signature in Meta's format."""
    digest = hmac_mod.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestHmacEdgeCases:
    """HMAC validation edge cases not covered by basic valid/invalid tests."""

    @pytest.mark.asyncio
    async def test_hmac_empty_body_valid_signature(self):
        """Empty body with valid HMAC passes signature check (parse fails gracefully)."""
        empty_body = b""
        signature = _sign(empty_body)

        with patch("app.services.whatsapp.webhook.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                whatsapp_app_secret=TEST_APP_SECRET,
                whatsapp_verify_token=TEST_VERIFY_TOKEN,
            )
            # Should not raise WhatsAppSignatureError (HMAC is valid)
            # But parsing will fail — process_webhook returns gracefully
            await WhatsAppWebhookService.process_webhook(empty_body, signature)

    @pytest.mark.asyncio
    async def test_hmac_body_tampered_after_signing(self):
        """Signing body A but sending body B produces 403."""
        original_body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
        tampered_body = json.dumps({"object": "whatsapp_business_account", "entry": [{"evil": True}]}).encode()
        signature = _sign(original_body)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhook/whatsapp",
                content=tampered_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_hmac_wrong_prefix(self):
        """Signature with sha512= prefix instead of sha256= is rejected."""
        body = json.dumps({"object": "whatsapp_business_account"}).encode()
        digest = hmac_mod.new(TEST_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        wrong_prefix_sig = f"sha512={digest}"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhook/whatsapp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": wrong_prefix_sig,
                },
            )

        assert response.status_code == 403

    def test_hmac_uses_constant_time_comparison(self):
        """_validate_hmac_signature uses hmac.compare_digest for timing safety."""
        body = b'{"test": true}'
        secret = TEST_APP_SECRET
        sig = _sign(body, secret)

        with (
            patch("app.services.whatsapp.webhook.get_settings") as mock_settings,
            patch("app.services.whatsapp.webhook.hmac.compare_digest", return_value=True) as mock_compare,
        ):
            mock_settings.return_value = MagicMock(whatsapp_app_secret=secret)
            WhatsAppWebhookService._validate_hmac_signature(body, sig)

        mock_compare.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_challenge_echoed(self):
        """GET verification echoes the challenge string exactly."""
        challenge = "unique_challenge_string_12345"

        with patch("app.services.whatsapp.webhook.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                whatsapp_verify_token=TEST_VERIFY_TOKEN,
                whatsapp_app_secret=TEST_APP_SECRET,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/webhook/whatsapp",
                    params={
                        "hub.mode": "subscribe",
                        "hub.verify_token": TEST_VERIFY_TOKEN,
                        "hub.challenge": challenge,
                    },
                )

        assert response.status_code == 200
        assert response.text == challenge

    @pytest.mark.asyncio
    async def test_webhook_missing_query_params(self):
        """GET without required query params returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/webhook/whatsapp")

        assert response.status_code == 422
