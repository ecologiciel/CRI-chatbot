"""Exercise staged WhatsApp inbox against a disposable PostgreSQL database only."""

import asyncio
import json
import secrets
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import Base, close_engine, get_engine, get_session_factory
from app.core.exceptions import CRIDecryptionError, TenantInactiveError
from app.core.tenant import TenantContext
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.schemas.whatsapp import IncomingMessage
from app.services.crypto.versioned_envelope import VersionedEnvelope, VersionedEnvelopeService
from app.services.whatsapp.inbox import persist_incoming_message


async def main():
    settings = get_settings()
    if (
        settings.environment != "development"
        or settings.postgres_host != "wa-inbox-pg"
        or settings.postgres_db != "wa_inbox_test"
    ):
        raise RuntimeError("Refusing to run outside the disposable WhatsApp test database")
    async with get_engine().begin() as conn:
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(
                sync, tables=[Tenant.__table__, TenantKey.__table__, WhatsAppInboxEvent.__table__]
            )
        )

    tenant_id = uuid.uuid4()
    master, data_key = secrets.token_bytes(32), secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    wrapped = nonce + AESGCM(master).encrypt(nonce, data_key, None)
    tenant = TenantContext(
        tenant_id, "synthetica", "Synthetic", "active", {"phone_number_id": "123"}
    )
    async with get_session_factory()() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Synthetic",
                slug=tenant.slug,
                region="Test",
                status=TenantStatus.active,
                whatsapp_config={"phone_number_id": "123"},
                public_config={},
            )
        )
        session.add(
            TenantKey(
                tenant_id=tenant_id,
                encrypted_key=wrapped,
                algorithm="AES-256-GCM",
                key_version=1,
                is_active=True,
            )
        )
        await session.commit()

    cipher = VersionedEnvelopeService(get_session_factory(), master.hex())
    message = IncomingMessage.model_validate(
        {
            "id": "synthetic-wamid",
            "from": "123456",
            "timestamp": "1",
            "type": "text",
            "text": {"body": "private synthetic body"},
        }
    )
    results = await asyncio.gather(
        *(persist_incoming_message(tenant, "123", message, None, cipher=cipher) for _ in range(4))
    )
    assert results.count(True) == 1 and results.count(False) == 3
    async with get_session_factory()() as session:
        events = (await session.execute(select(WhatsAppInboxEvent))).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert "private synthetic body" not in event.ciphertext
    plaintext = await cipher.decrypt(
        VersionedEnvelope(event.key_version, event.ciphertext),
        tenant_id=tenant_id,
        purpose="wa_inbox",
        record_id=event.id,
    )
    assert json.loads(plaintext)["message"]["text"]["body"] == "private synthetic body"
    try:
        await cipher.decrypt(
            VersionedEnvelope(event.key_version, event.ciphertext),
            tenant_id=tenant_id,
            purpose="wa_inbox",
            record_id=uuid.uuid4(),
        )
    except CRIDecryptionError:
        pass
    else:
        raise AssertionError("Ciphertext accepted under another record")
    try:
        await persist_incoming_message(tenant, "999", message, None, cipher=cipher)
    except TenantInactiveError:
        pass
    else:
        raise AssertionError("Changed channel accepted")
    await close_engine()
    print("ISOLATED_INBOX_POSTGRES_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
