import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.whatsapp.inbox_intake as intake
from app.core.exceptions import WhatsAppSignatureError


def payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "account",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "123", "phone_number_id": "123"},
                            "messages": [
                                {"id": "wamid.1", "from": "123", "timestamp": "1", "type": "text"}
                            ],
                        },
                    }
                ],
            }
        ],
    }


def setup_intake(monkeypatch):
    verify = MagicMock()
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(intake.WhatsAppWebhookService, "_validate_hmac_signature", verify)
    monkeypatch.setattr(intake, "get_session_factory", lambda: None)
    monkeypatch.setattr(intake, "get_settings", lambda: MagicMock(kms_master_key="00" * 32))
    monkeypatch.setattr(intake, "VersionedEnvelopeService", MagicMock())
    monkeypatch.setattr(
        intake.TenantResolver, "from_phone_number_id", AsyncMock(return_value="tenant")
    )
    monkeypatch.setattr(intake, "persist_incoming_message", persist)
    return verify, persist


@pytest.mark.asyncio
async def test_intake_authenticates_then_commits(monkeypatch):
    verify, persist = setup_intake(monkeypatch)
    body = json.dumps(payload()).encode()
    await intake.persist_authenticated_webhook(body, "signature")
    verify.assert_called_once_with(body, "signature")
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_bad_signature_never_persists(monkeypatch):
    verify, persist = setup_intake(monkeypatch)
    verify.side_effect = WhatsAppSignatureError("invalid")
    with pytest.raises(WhatsAppSignatureError):
        await intake.persist_authenticated_webhook(b"{}", None)
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_batch_rejected_before_any_writes(monkeypatch):
    _, persist = setup_intake(monkeypatch)
    event = payload()
    event["entry"][0]["changes"][0]["value"]["statuses"] = [
        {"id": "wamid.2", "status": "delivered", "timestamp": "1", "recipient_id": "123"}
    ]
    with pytest.raises(intake.UnsupportedInboxEventError):
        await intake.persist_authenticated_webhook(json.dumps(event).encode(), "signature")
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_failure_is_not_acknowledged(monkeypatch):
    _, persist = setup_intake(monkeypatch)
    persist.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await intake.persist_authenticated_webhook(json.dumps(payload()).encode(), "signature")
