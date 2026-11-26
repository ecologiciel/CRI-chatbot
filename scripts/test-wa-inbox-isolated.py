"""Exercise staged WhatsApp inbox against a disposable PostgreSQL database only."""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from sqlalchemy import select, text, update

from app.core.config import get_settings
from app.api.v1.whatsapp_operations import (
    ReviewRequest,
    event_detail,
    list_events,
    review_event,
)
from app.core.database import Base, close_engine, get_engine, get_session_factory
from app.core.exceptions import CRIDecryptionError, TenantInactiveError
from app.core.tenant import TenantContext
from app.models.enums import TenantStatus
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
from app.models.whatsapp_inbox import WhatsAppInboxEvent
from app.models.whatsapp_status_inbox import WhatsAppStatusEvent
from app.schemas.whatsapp import IncomingMessage, StatusInfo
from app.schemas.auth import AdminTokenPayload
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
from app.services.whatsapp.inbox_retention import _redact_tenant
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
                    [Tenant.__table__, TenantKey.__table__, AuditLog.__table__]
                    if os.getenv("WA_INBOX_ALEMBIC_TEST") == "1"
                    else [
                        Tenant.__table__,
                        TenantKey.__table__,
                        AuditLog.__table__,
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
                whatsapp_config={"phone_number_id": "789"},
                public_config={},
            )
        )
        await session.flush()
        session.add(
            WhatsAppStatusEvent(
                tenant_id=other_tenant_id,
                phone_number_id="789",
                fingerprint="b" * 64,
                ciphertext="synthetic",
                key_version=1,
                state="uncertain",
            )
        )
        await session.commit()
    operations = await list_events(
        kind="status", state="uncertain", limit=50, offset=0, tenant=tenant, _admin=None
    )
    assert len(operations["events"]) == 1
    assert set(operations["events"][0]) == {
        "id",
        "state",
        "attempts",
        "created_at",
        "updated_at",
        "redacted_at",
    }
    review_id = uuid.UUID(operations["events"][0]["id"])
    admin = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role="admin_tenant",
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    with patch(
        "app.api.v1.whatsapp_operations.VersionedEnvelopeService", return_value=cipher
    ):
        detail = await event_detail(
            review_id, kind="status", tenant=tenant, admin=admin
        )
    assert detail["provider_message_id"] == "status-wamid"
    assert detail["recipient_masked"] == "***0001"
    assert "212600000001" not in json.dumps(detail)
    async with get_engine().begin() as conn:
        await conn.execute(
            text("""
            CREATE FUNCTION public.reject_synthetic_audit() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END $$
        """)
        )
        await conn.execute(
            text("""
            CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON public.audit_logs
            FOR EACH ROW EXECUTE FUNCTION public.reject_synthetic_audit()
        """)
        )
    try:
        await review_event(
            review_id,
            ReviewRequest(action="follow_up"),
            kind="status",
            tenant=tenant,
            admin=admin,
        )
        raise AssertionError("Review unexpectedly succeeded without audit")
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
    async with get_engine().begin() as conn:
        await conn.execute(
            text("DROP TRIGGER synthetic_audit_failure ON public.audit_logs")
        )
        await conn.execute(text("DROP FUNCTION public.reject_synthetic_audit()"))
    async with get_session_factory()() as session:
        current = (
            await session.execute(
                select(WhatsAppStatusEvent.state).where(
                    WhatsAppStatusEvent.id == review_id
                )
            )
        ).scalar_one()
    assert current == "uncertain"
    assert (
        await review_event(
            review_id,
            ReviewRequest(action="follow_up"),
            kind="status",
            tenant=tenant,
            admin=admin,
        )
    )["state"] == "follow_up"
    assert (
        await review_event(
            review_id,
            ReviewRequest(action="resolve"),
            kind="status",
            tenant=tenant,
            admin=admin,
        )
    )["state"] == "resolved"
    async with get_session_factory()() as session:
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.resource_id == str(review_id))
                )
            )
            .scalars()
            .all()
        )
        other_id = (
            await session.execute(
                select(WhatsAppStatusEvent.id).where(
                    WhatsAppStatusEvent.tenant_id == other_tenant_id
                )
            )
        ).scalar_one()
    assert len(logs) == 3 and all(log.tenant_slug == tenant.slug for log in logs)
    assert sum(log.action == "wa_inbox_view" for log in logs) == 1
    assert sum(log.action == "wa_inbox_review" for log in logs) == 2
    for target, expected in ((review_id, 409), (other_id, 404)):
        try:
            await review_event(
                target,
                ReviewRequest(action="resolve"),
                kind="status",
                tenant=tenant,
                admin=admin,
            )
            raise AssertionError("Unexpected review access")
        except HTTPException as exc:
            assert exc.status_code == expected
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
        # An in-flight message must not prevent a duplicate webhook from
        # being acknowledged after its independent transaction commits.
        duplicate = await asyncio.wait_for(
            persist_incoming_message(tenant, "123", message, None, cipher=cipher),
            timeout=5,
        )
        assert duplicate is False
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
    if os.getenv("WA_INBOX_ARQ_TEST") == "1":
        from arq.connections import RedisSettings, create_pool
        from arq.worker import Worker
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        import app.api.v1.webhook as webhook_api
        import app.services.whatsapp.inbox_execution as execution
        import app.services.whatsapp.inbox_intake as intake
        import app.services.whatsapp.webhook as webhook_service
        from app.services.crypto.startup_guard import assert_master_key_consistent
        from app.services.whatsapp.handler import HandlingOutcome
        from app.workers.whatsapp_inbox import WorkerSettings, poll_incoming

        fresh = message.model_copy(update={"id": "synthetic-worker-wamid"})
        raw = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "synthetic-account",
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {
                                        "phone_number_id": "123",
                                        "display_phone_number": "123",
                                    },
                                    "messages": [
                                        fresh.model_dump(mode="json", by_alias=True)
                                    ],
                                    "statuses": [status.model_dump(mode="json")],
                                },
                            }
                        ],
                    }
                ],
            }
        ).encode()
        secret = "synthetic-webhook-secret"
        signature = (
            "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        )
        api_settings = MagicMock(
            whatsapp_durable_inbox_enabled=True,
            whatsapp_webhook_max_body_bytes=1_048_576,
            webhook_proxy_shared_secret="",
        )
        app = FastAPI()
        app.include_router(webhook_api.router, prefix="/api/v1")
        with (
            patch.object(webhook_api, "get_settings", return_value=api_settings),
            patch.object(
                webhook_service,
                "get_settings",
                return_value=MagicMock(whatsapp_app_secret=secret),
            ),
            patch.object(
                intake,
                "get_settings",
                return_value=MagicMock(kms_master_key=master.hex()),
            ),
            patch.object(intake, "VersionedEnvelopeService", return_value=cipher),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                denied = await client.post(
                    "/api/v1/webhook/whatsapp",
                    content=raw,
                    headers={"X-Hub-Signature-256": "sha256=invalid"},
                )
                assert denied.status_code == 403
                for _ in range(2):
                    response = await client.post(
                        "/api/v1/webhook/whatsapp",
                        content=raw,
                        headers={"X-Hub-Signature-256": signature},
                    )
                    assert response.status_code == 200
        redis = await create_pool(
            RedisSettings(host="wa-inbox-redis", password="wa_test")
        )
        try:
            await assert_master_key_consistent(get_session_factory(), master)
            job = await redis.enqueue_job(
                "poll_incoming", _queue_name=WorkerSettings.queue_name
            )
            handler = MagicMock()
            handler.handle_message = AsyncMock(return_value=HandlingOutcome.accepted)
            with (
                patch.object(
                    execution, "VersionedEnvelopeService", return_value=cipher
                ),
                patch.object(execution, "get_message_handler", return_value=handler),
            ):
                worker = Worker(
                    functions=[poll_incoming],
                    queue_name=WorkerSettings.queue_name,
                    redis_pool=redis,
                    burst=True,
                    handle_signals=False,
                    max_tries=1,
                    on_startup=WorkerSettings.on_startup,
                    on_shutdown=WorkerSettings.on_shutdown,
                )
                await worker.async_run()
            assert await job.result(timeout=5) == "finalized"
            handler.handle_message.assert_awaited_once()
            async with get_session_factory()() as session:
                state = (
                    await session.execute(
                        select(WhatsAppInboxEvent.state).where(
                            WhatsAppInboxEvent.provider_message_id == fresh.id
                        )
                    )
                ).scalar_one()
            assert state == "completed"
            await worker.close()
        finally:
            await redis.aclose()
        print("ISOLATED_INBOX_ARQ_OK", flush=True)
    now = datetime.now(UTC)
    old = now - timedelta(days=91)
    pending_id, expired_id, live_id, old_status_id = (uuid.uuid4() for _ in range(4))
    async with get_session_factory()() as session:
        await session.execute(
            update(WhatsAppStatusEvent)
            .where(WhatsAppStatusEvent.id == other_id)
            .values(created_at=old, ciphertext="other-tenant-sensitive")
        )
        for event_id, state, lease_until in (
            (pending_id, "pending", None),
            (expired_id, "processing", now - timedelta(seconds=1)),
            (live_id, "processing", now + timedelta(minutes=5)),
        ):
            session.add(
                WhatsAppInboxEvent(
                    id=event_id,
                    tenant_id=tenant_id,
                    phone_number_id="123",
                    provider_message_id="retention-" + str(event_id),
                    ciphertext="synthetic-sensitive",
                    key_version=1,
                    state=state,
                    created_at=old,
                    lease_until=lease_until,
                    lease_token=uuid.uuid4() if lease_until else None,
                )
            )
        session.add(
            WhatsAppStatusEvent(
                id=old_status_id,
                tenant_id=tenant_id,
                phone_number_id="123",
                fingerprint="c" * 64,
                ciphertext="synthetic-sensitive",
                key_version=1,
                state="pending",
                created_at=old,
            )
        )
        await session.commit()
    counts = await _redact_tenant(tenant_id, tenant.slug, 90, now)
    assert counts == {"messages": 2, "statuses": 1}
    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(WhatsAppInboxEvent).where(
                        WhatsAppInboxEvent.id.in_([pending_id, expired_id, live_id])
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        old_status = (
            await session.execute(
                select(WhatsAppStatusEvent).where(
                    WhatsAppStatusEvent.id == old_status_id
                )
            )
        ).scalar_one()
        other_status = (
            await session.execute(
                select(WhatsAppStatusEvent).where(WhatsAppStatusEvent.id == other_id)
            )
        ).scalar_one()
        purge_audit = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "wa_payload_purge",
                        AuditLog.tenant_slug == tenant.slug,
                    )
                )
            )
            .scalars()
            .all()
        )
    for event_id in (pending_id, expired_id):
        assert by_id[event_id].state == "uncertain" and by_id[event_id].ciphertext == ""
        assert (
            by_id[event_id].redacted_at is not None
            and by_id[event_id].lease_token is None
        )
    assert (
        by_id[live_id].state == "processing"
        and by_id[live_id].ciphertext == "synthetic-sensitive"
    )
    assert old_status.state == "uncertain" and old_status.ciphertext == ""
    assert (
        other_status.ciphertext == "other-tenant-sensitive"
        and other_status.redacted_at is None
    )
    assert len(purge_audit) == 1
    try:
        await event_detail(pending_id, kind="message", tenant=tenant, admin=admin)
        raise AssertionError("Redacted payload was disclosed")
    except HTTPException as exc:
        assert exc.status_code == 410
    audit_failure_id = uuid.uuid4()
    async with get_session_factory()() as session:
        session.add(
            WhatsAppInboxEvent(
                id=audit_failure_id,
                tenant_id=tenant_id,
                phone_number_id="123",
                provider_message_id="retention-" + str(audit_failure_id),
                ciphertext="synthetic-sensitive",
                key_version=1,
                state="pending",
                created_at=old,
            )
        )
        await session.commit()
    async with get_engine().begin() as conn:
        await conn.execute(
            text("""
            CREATE FUNCTION public.reject_synthetic_purge_audit() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END $$
        """)
        )
        await conn.execute(
            text("""
            CREATE TRIGGER synthetic_purge_audit_failure BEFORE INSERT ON public.audit_logs
            FOR EACH ROW EXECUTE FUNCTION public.reject_synthetic_purge_audit()
        """)
        )
    try:
        await _redact_tenant(tenant_id, tenant.slug, 90, now)
        raise AssertionError("Retention unexpectedly committed without audit")
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
    async with get_engine().begin() as conn:
        await conn.execute(
            text("DROP TRIGGER synthetic_purge_audit_failure ON public.audit_logs")
        )
        await conn.execute(text("DROP FUNCTION public.reject_synthetic_purge_audit()"))
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(WhatsAppInboxEvent).where(
                    WhatsAppInboxEvent.id == audit_failure_id
                )
            )
        ).scalar_one()
        assert row.state == "pending" and row.ciphertext == "synthetic-sensitive"
    assert (await _redact_tenant(tenant_id, tenant.slug, 90, now))["messages"] == 1
    print("ISOLATED_INBOX_RETENTION_OK", flush=True)
    await close_engine()
    print("ISOLATED_INBOX_POSTGRES_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
