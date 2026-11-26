"""Exercise staged WhatsApp inbox against a disposable PostgreSQL database only."""

import asyncio
import json
import os
import secrets
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, text, update

from app.core.config import get_settings
from app.api.v1.whatsapp_operations import list_events
from app.core.database import Base, close_engine, get_engine, get_session_factory
from app.core.exceptions import CRIDecryptionError, TenantInactiveError
from app.core.tenant import TenantContext
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.whatsapp import IncomingMessage, StatusInfo
from app.services.crypto.versioned_envelope import (
    VersionedEnvelope,
    VersionedEnvelopeService,
)
from app.services.whatsapp.inbox import persist_incoming_message
from app.services.whatsapp.inbox_channel import protect_claim_channel
from app.services.whatsapp.inbox_leases import (
    claim_next,
    finish_claim,
    quarantine_expired,
    renew_claim,
)
from app.services.whatsapp.inbox_payload import decrypt_claim
from app.services.whatsapp.status_batch import run_status_batch
from app.services.whatsapp.status_inbox import persist_delivery_status
from app.services.whatsapp.status_projection import apply_status_event


async def main():
    settings = get_settings()
    if (
        settings.environment != "development"
        or settings.postgres_host != "wa-inbox-pg"
        or settings.postgres_db != "wa_inbox_test"
    ):
        raise RuntimeError(
            "Refusing to run outside the disposable WhatsApp test database"
        )
    async with get_engine().begin() as conn:
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=(
                    [Tenant.__table__, TenantKey.__table__]
                    if os.getenv("WA_INBOX_ALEMBIC_TEST") == "1"
                    else [
                        Tenant.__table__,
                        TenantKey.__table__,
                        WhatsAppInboxEvent.__table__,
                        WhatsAppStatusEvent.__table__,
                    ]
                ),
            )
        )
    if os.getenv("WA_INBOX_ALEMBIC_TEST") == "1":
        for args in (("stamp", "0017"), ("upgrade", "0019")):
            process = await asyncio.create_subprocess_exec("alembic", *args, cwd="/app")
            if await process.wait() != 0:
                raise RuntimeError("Isolated Alembic migration failed")

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
    status = StatusInfo(
        id="status-wamid",
        status="delivered",
        timestamp="123",
        recipient_id="212600000001",
    )
    status_results = await asyncio.gather(
        *(
            persist_delivery_status(
                tenant, "123", status, cipher=cipher, fingerprint_key=master
            )
            for _ in range(4)
        )
    )
    assert status_results.count(True) == 1 and status_results.count(False) == 3
    async with get_session_factory()() as session:
        status_rows = (
            (await session.execute(select(WhatsAppStatusEvent))).scalars().all()
        )
    assert len(status_rows) == 1 and "212600000001" not in status_rows[0].ciphertext
    status_plaintext = await cipher.decrypt(
        VersionedEnvelope(status_rows[0].key_version, status_rows[0].ciphertext),
        tenant_id=tenant_id,
        purpose="wa_status",
        record_id=status_rows[0].id,
    )
    assert json.loads(status_plaintext)["status"]["status"] == "delivered"
    async with get_engine().begin() as conn:
        await conn.execute(text("CREATE SCHEMA tenant_synthetica"))
        await conn.execute(text("CREATE SCHEMA tenant_syntheticb"))
        await conn.execute(
            text("""
            CREATE TABLE tenant_synthetica.messages (
                id uuid PRIMARY KEY, conversation_id uuid NOT NULL,
                direction public.messagedirection NOT NULL, type public.messagetype NOT NULL,
                content text, media_url varchar(500), chunk_ids jsonb NOT NULL DEFAULT '[]',
                whatsapp_message_id varchar(100), metadata jsonb,
                timestamp timestamptz NOT NULL DEFAULT now(),
                created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        )
        await conn.execute(
            text(
                "CREATE TABLE tenant_syntheticb.messages (LIKE tenant_synthetica.messages INCLUDING ALL)"
            )
        )
    assert await apply_status_event(status_rows[0].id, cipher=cipher) == "waiting"
    assert await apply_status_event(status_rows[0].id, cipher=cipher) == "deferred"
    async with get_engine().begin() as conn:
        await conn.execute(
            text("""
            INSERT INTO tenant_synthetica.messages
                (id, conversation_id, direction, type, whatsapp_message_id, metadata)
            VALUES (:id, :conversation, 'outbound', 'text', 'status-wamid', '{"delivery_state":"accepted"}')
        """),
            {"id": uuid.uuid4(), "conversation": uuid.uuid4()},
        )
        await conn.execute(
            text("""
            INSERT INTO tenant_syntheticb.messages
                (id, conversation_id, direction, type, whatsapp_message_id, metadata)
            VALUES (:id, :conversation, 'outbound', 'text', 'status-wamid', '{"delivery_state":"accepted"}')
        """),
            {"id": uuid.uuid4(), "conversation": uuid.uuid4()},
        )
    async with get_session_factory()() as session:
        await session.execute(
            update(WhatsAppStatusEvent)
            .where(WhatsAppStatusEvent.id == status_rows[0].id)
            .values(next_attempt_at=text("clock_timestamp() - interval '1 second'"))
        )
        await session.commit()
    assert await apply_status_event(status_rows[0].id, cipher=cipher) == "applied"
    assert await apply_status_event(status_rows[0].id, cipher=cipher) == "applied"
    async with get_engine().connect() as conn:
        delivery = (
            await conn.execute(
                text(
                    "SELECT metadata->>'delivery_state' FROM tenant_synthetica.messages"
                )
            )
        ).scalar_one()
    assert delivery == "delivered"
    async with get_engine().connect() as conn:
        other_delivery = (
            await conn.execute(
                text(
                    "SELECT metadata->>'delivery_state' FROM tenant_syntheticb.messages"
                )
            )
        ).scalar_one()
    assert other_delivery == "accepted"
    for provider_state, expected in (("sent", "applied"), ("failed", "uncertain")):
        next_status = StatusInfo(
            id="status-wamid",
            status=provider_state,
            timestamp="124",
            recipient_id="212600000001",
        )
        assert await persist_delivery_status(
            tenant, "123", next_status, cipher=cipher, fingerprint_key=master
        )
        async with get_session_factory()() as session:
            pending_id = (
                await session.execute(
                    select(WhatsAppStatusEvent.id).where(
                        WhatsAppStatusEvent.state == "pending"
                    )
                )
            ).scalar_one()
        assert isinstance(pending_id, uuid.UUID)
        counts = await run_status_batch(cipher=cipher)
        assert counts.get(expected) == 1
    other_tenant_id = uuid.uuid4()
    async with get_session_factory()() as session:
        session.add(
            Tenant(
                id=other_tenant_id,
                name="Other",
                slug="syntheticb",
                region="Test",
                status=TenantStatus.active,
                whatsapp_config={"phone_number_id": "456"},
                public_config={},
            )
        )
        await session.flush()
        session.add(
            WhatsAppStatusEvent(
                tenant_id=other_tenant_id,
                phone_number_id="456",
                fingerprint="b" * 64,
                ciphertext="synthetic",
                key_version=1,
                state="uncertain",
            )
        )
        await session.commit()
    operations = await list_events(
        kind="status", state="uncertain", limit=50, tenant=tenant, _admin=None
    )
    assert len(operations["events"]) == 1
    assert set(operations["events"][0]) == {
        "id",
        "state",
        "attempts",
        "created_at",
        "updated_at",
    }
    async with get_engine().connect() as conn:
        delivery = (
            await conn.execute(
                text(
                    "SELECT metadata->>'delivery_state' FROM tenant_synthetica.messages"
                )
            )
        ).scalar_one()
    assert delivery == "delivered"
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
        *(
            persist_incoming_message(tenant, "123", message, None, cipher=cipher)
            for _ in range(4)
        )
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

    claims = await asyncio.gather(*(claim_next(lease_seconds=30) for _ in range(4)))
    active = [claim for claim in claims if claim is not None]
    assert len(active) == 1
    claim = active[0]
    if claim.id != event.id:
        async with get_session_factory()() as session:
            rows = (await session.execute(select(WhatsAppInboxEvent))).scalars().all()
            details = [(r.id, r.tenant_id, r.lease_token, r.state) for r in rows]
        raise AssertionError(
            f"Unexpected claimed event: {claim.id!r} != {event.id!r}; "
            f"claim tenant={claim.tenant_id!r} token={claim.lease_token!r}; rows={details!r}"
        )
    decoded = await decrypt_claim(claim, cipher)
    assert decoded.message.id == message.id

    update_started = asyncio.Event()

    async def change_channel():
        async with get_session_factory()() as session:
            update_started.set()
            await session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(whatsapp_config={"phone_number_id": "456"})
            )
            await session.commit()

    async with protect_claim_channel(claim) as protected:
        assert protected.id == tenant_id
        updater = asyncio.create_task(change_channel())
        await update_started.wait()
        await asyncio.sleep(0.3)
        assert not updater.done(), "Channel update bypassed the tenant lock"
    await asyncio.wait_for(updater, timeout=5)
    try:
        async with protect_claim_channel(claim):
            raise AssertionError("Reassigned channel was accepted")
    except TenantInactiveError:
        pass
    async with get_session_factory()() as session:
        await session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(whatsapp_config={"phone_number_id": "123"})
        )
        await session.commit()
    assert await renew_claim(claim.id, uuid.uuid4(), lease_seconds=30) is False
    assert await renew_claim(claim.id, claim.lease_token, lease_seconds=30) is True
    assert await finish_claim(claim.id, uuid.uuid4(), uncertain=False) is False
    async with get_session_factory()() as session:
        await session.execute(
            update(WhatsAppInboxEvent)
            .where(WhatsAppInboxEvent.id == claim.id)
            .values(lease_until=text("clock_timestamp() - interval '1 second'"))
        )
        await session.commit()
    assert await finish_claim(claim.id, claim.lease_token, uncertain=False) is False
    assert await quarantine_expired() == 1
    assert await finish_claim(claim.id, claim.lease_token, uncertain=True) is False
    assert await claim_next(lease_seconds=30) is None
    async with get_session_factory()() as session:
        state = (
            await session.execute(
                select(WhatsAppInboxEvent.state).where(
                    WhatsAppInboxEvent.id == claim.id
                )
            )
        ).scalar_one()
    assert state == "uncertain"
    await close_engine()
    print("ISOLATED_INBOX_POSTGRES_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
