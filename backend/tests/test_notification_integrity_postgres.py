"""Recipient and status checks against a disposable migrated database."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenant import TenantContext
from app.services.notification.service import NotificationEventType, NotificationService

URL = os.getenv("TEST_NOTIFICATION_INTEGRITY_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable migrated PostgreSQL")


@pytest_asyncio.fixture
async def environment(monkeypatch):
    url = make_url(URL)
    if not url.database or not url.database.startswith("ragtest_"):
        raise RuntimeError("Refusing non-fixture PostgreSQL")
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.tenant.get_session_factory", lambda: sessions)
    first, second, dossier = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    suffix = str(uuid.uuid4().int % 10**10).zfill(10)
    tenant = TenantContext(
        id=uuid.uuid4(), slug="template", name="Fixture", status="active", whatsapp_config=None
    )
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(text("SELECT current_database()")) == url.database
            await conn.execute(
                text(
                    "INSERT INTO tenant_template.contacts (id,phone,name,language,opt_in_status) VALUES (:id,:phone,'Fixture','fr','opted_in'),(:id2,:phone2,'Other','fr','opted_in')"
                ),
                {"id": first, "phone": "+19" + suffix, "id2": second, "phone2": "+18" + suffix},
            )
            await conn.execute(
                text(
                    "INSERT INTO tenant_template.dossiers (id,numero,contact_id,statut) VALUES (:id,:numero,:contact,'rejete')"
                ),
                {"id": dossier, "numero": "fixture-" + dossier.hex, "contact": first},
            )
        sender = AsyncMock()
        sender.send_template.return_value = "fixture-wamid"
        yield (
            NotificationService(sender, AsyncMock()),
            sender,
            tenant,
            engine,
            first,
            second,
            dossier,
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM tenant_template.dossiers WHERE id=:id"), {"id": dossier}
            )
            await conn.execute(
                text("DELETE FROM tenant_template.contacts WHERE id IN (:one,:two)"),
                {"one": first, "two": second},
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_recipient_and_status_are_authoritative(environment):
    service, sender, tenant, _, first, second, dossier = environment
    kwargs = dict(
        event_type=NotificationEventType.decision_finale, template_name="fixture", sender=sender
    )
    reason, _ = await service._send_manual_with_current_data(tenant, second, dossier, **kwargs)
    assert reason == "dossier_contact_mismatch"
    sender.send_template.assert_not_awaited()
    reason, result = await service._send_manual_with_current_data(tenant, first, dossier, **kwargs)
    assert reason is None and result == "fixture-wamid"
    assert (
        sender.send_template.await_args.kwargs["components"][0]["parameters"][2]["text"] == "Rejeté"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("language, expected", [("ar", "مرفوض"), ("en", "Rejected")])
async def test_rejected_decision_uses_actual_status_in_each_language(
    environment, language, expected
):
    service, sender, tenant, engine, first, _, dossier = environment
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE tenant_template.contacts SET language=CAST(:language AS public.language) WHERE id=:id"
            ),
            {"language": language, "id": first},
        )
    reason, result = await service._send_manual_with_current_data(
        tenant,
        first,
        dossier,
        event_type=NotificationEventType.decision_finale,
        template_name="fixture",
        sender=sender,
    )
    assert reason is None and result == "fixture-wamid"
    assert (
        sender.send_template.await_args.kwargs["components"][0]["parameters"][2]["text"] == expected
    )


@pytest.mark.asyncio
async def test_automatic_stale_event_is_not_sent(environment):
    service, sender, tenant, _, first, second, dossier = environment
    kwargs = dict(
        template_name="fixture",
        language_code="fr",
        components=[],
        dossier_id=dossier,
        expected_numero="fixture-" + dossier.hex,
        expected_status="valide",
        expected_name="Fixture",
    )
    reason, _ = await service._send_with_current_consent(tenant, first, **kwargs)
    assert reason == "dossier_changed"
    kwargs["expected_status"] = "rejete"
    kwargs["expected_name"] = "Other"
    reason, _ = await service._send_with_current_consent(tenant, second, **kwargs)
    assert reason == "dossier_contact_mismatch"
    sender.send_template.assert_not_awaited()


@pytest.mark.asyncio
async def test_recipient_and_dossier_are_locked_during_provider_call(environment):
    service, sender, tenant, engine, first, _, dossier = environment
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(**_):
        entered.set()
        await release.wait()
        return "fixture-wamid"

    sender.send_template.side_effect = send
    task = asyncio.create_task(
        service._send_manual_with_current_data(
            tenant,
            first,
            dossier,
            event_type=NotificationEventType.decision_finale,
            template_name="fixture",
            sender=sender,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        for statement, ident in (
            ("UPDATE tenant_template.contacts SET opt_in_status='opted_out' WHERE id=:id", first),
            ("UPDATE tenant_template.dossiers SET statut='valide' WHERE id=:id", dossier),
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL lock_timeout='100ms'"))
                    await conn.execute(text(statement), {"id": ident})
    finally:
        release.set()
        result = await asyncio.wait_for(task, timeout=5)
    assert result == (None, "fixture-wamid")
