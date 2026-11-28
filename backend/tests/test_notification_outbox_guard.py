"""Checks for stale dossiers, recipients and tenant/channel changes before send."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import DossierStatut, OptInStatus, TenantStatus
from app.services.notification.outbox import NotificationClaim
from app.services.notification.service import NotificationService


@pytest.mark.asyncio()
@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, None),
        ("claim", "claim_lost"),
        ("tenant", "tenant_or_channel_changed"),
        ("channel", "tenant_or_channel_changed"),
        ("recipient", "recipient_changed"),
        ("status", "dossier_superseded"),
        ("later", "dossier_superseded"),
        ("optout", "opted_out"),
    ],
)
async def test_guard_refuses_stale_or_unauthorized_sends(failure, expected, encrypted):
    tenant_id, dossier_id, contact_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim = NotificationClaim(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), dossier_id, contact_id, 7)
    channel = {"phone_number_id": "123", "access_token": "test"}
    tenant = MagicMock(id=tenant_id, whatsapp_config=channel)
    tenant_row = SimpleNamespace(
        id=tenant_id, slug="alpha", name="Institution",
        status=TenantStatus.inactive if failure == "tenant" else TenantStatus.active,
        whatsapp_config={} if failure == "channel" else channel,
    )
    decoded = tenant_row.whatsapp_config
    if encrypted:
        tenant_row.whatsapp_config = {"phone_number_id": "123", "_format": "sealed"}
    dossier = SimpleNamespace(
        contact_id=uuid.uuid4() if failure == "recipient" else contact_id,
        statut=DossierStatut.rejete if failure == "status" else DossierStatut.valide,
    )
    history = SimpleNamespace(new_value="valide", old_value="en_attente")
    contact = SimpleNamespace(
        opt_in_status=OptInStatus.opted_out if failure == "optout" else OptInStatus.opted_in,
        phone="+212600000000",
    )
    values = [
        None if failure == "claim" else claim.event_id,
        tenant_row,
        dossier,
        history,
        uuid.uuid4() if failure == "later" else None,
        contact,
    ]
    results = []
    for value in values:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    session = AsyncMock()
    session.execute.side_effect = results
    tenant.db_session.return_value.__aenter__.return_value = session
    sender = AsyncMock()
    sender.send_template.return_value = "wamid.accepted"
    service = NotificationService(sender, AsyncMock())
    from contextlib import nullcontext
    resolver = AsyncMock(return_value=SimpleNamespace(whatsapp_config=decoded))
    resolver_patch = patch("app.services.notification.service.TenantResolver._build_context", resolver) if encrypted else nullcontext()
    with resolver_patch:
        reason, wamid = await service._send_with_current_consent(
            tenant,
            contact_id,
            template_name="template",
            language_code="fr",
            components=[],
            durable_claim=claim,
            expected_status="valide",
            expected_old_status="en_attente",
        )
    if encrypted and failure not in {"claim", "tenant"}:
        resolver.assert_awaited_once_with(tenant_row, session=session)
    assert reason == expected
    if expected:
        assert wamid is None
        sender.send_template.assert_not_awaited()
    else:
        assert wamid == "wamid.accepted"
        sender.send_template.assert_awaited_once()
