"""Authenticated inbox persistence must be tenant-bound and commit before return."""

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import TenantInactiveError
from app.models.enums import TenantStatus
from app.schemas.whatsapp import ContactInfo, IncomingMessage
from app.services.crypto.versioned_envelope import VersionedEnvelope
from app.services.whatsapp.inbox import persist_incoming_message


@pytest.mark.asyncio
@pytest.mark.parametrize("inserted,commit_fails", [(True, False), (False, False), (True, True)])
async def test_persist_is_encrypted_deduplicated_and_committed(inserted, commit_fails):
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="alpha")
    message = IncomingMessage.model_validate(
        {
            "id": "wamid.test",
            "from": "1234",
            "timestamp": "1",
            "type": "text",
            "text": {"body": "privé"},
        }
    )
    contacts = [
        ContactInfo(profile={"name": "Mine"}, wa_id="1234"),
        ContactInfo(profile={"name": "Other"}, wa_id="9876"),
    ]
    row = MagicMock()
    row.scalar_one_or_none.return_value = SimpleNamespace(
        status=TenantStatus.active, whatsapp_config={"phone_number_id": "777"}
    )
    insertion = MagicMock()
    insertion.scalar_one_or_none.return_value = uuid.uuid4() if inserted else None
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[row, insertion]),
        commit=AsyncMock(
            side_effect=RuntimeError("database unavailable") if commit_fails else None
        ),
    )

    @asynccontextmanager
    async def factory():
        yield session

    @asynccontextmanager
    async def guard(_tenant):
        yield

    cipher = SimpleNamespace(encrypt=AsyncMock(return_value=VersionedEnvelope(3, "encrypted")))
    with (
        patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.inbox.protect_ingestion", guard),
    ):
        if commit_fails:
            with pytest.raises(RuntimeError, match="database unavailable"):
                await persist_incoming_message(tenant, "777", message, contacts, cipher=cipher)
        else:
            result = await persist_incoming_message(tenant, "777", message, contacts, cipher=cipher)
            assert result is inserted
    session.commit.assert_awaited_once()
    plaintext = json.loads(cipher.encrypt.await_args.args[0])
    assert plaintext["message"]["text"]["body"] == "privé"
    assert [contact["wa_id"] for contact in plaintext["contacts"]] == ["1234"]
    statement = session.execute.await_args_list[1].args[0]
    params = statement.compile().params
    assert "privé" not in str(params)
    assert "encrypted" in params.values()


@pytest.mark.asyncio
async def test_changed_channel_is_not_stored():
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="alpha")
    message = IncomingMessage.model_validate(
        {
            "id": "wamid.test",
            "from": "1234",
            "timestamp": "1",
            "type": "text",
            "text": {"body": "x"},
        }
    )
    row = MagicMock()
    row.scalar_one_or_none.return_value = SimpleNamespace(
        status=TenantStatus.active, whatsapp_config={"phone_number_id": "999"}
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=row), commit=AsyncMock())

    @asynccontextmanager
    async def factory():
        yield session

    @asynccontextmanager
    async def guard(_tenant):
        yield

    cipher = SimpleNamespace(encrypt=AsyncMock(return_value=VersionedEnvelope(1, "encrypted")))
    with (
        patch("app.services.whatsapp.inbox.get_session_factory", return_value=factory),
        patch("app.services.whatsapp.inbox.protect_ingestion", guard),
        pytest.raises(TenantInactiveError),
    ):
        await persist_incoming_message(tenant, "777", message, None, cipher=cipher)
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
