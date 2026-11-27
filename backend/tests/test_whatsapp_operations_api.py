import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.v1.whatsapp_operations import ReviewRequest, availability, event_detail, review_event
from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload


@pytest.mark.asyncio
async def test_disabled_intake_does_not_claim_worker_or_query_backlog():
    tenant = TenantContext(uuid.uuid4(), "alpha", "Alpha", "active", None)
    with (
        patch("app.api.v1.whatsapp_operations.get_settings", return_value=MagicMock(whatsapp_durable_inbox_enabled=False)),
        patch("app.api.v1.whatsapp_operations.get_session_factory") as factory,
        patch("app.api.v1.whatsapp_operations.get_redis") as redis,
    ):
        result = await availability(tenant=tenant, _admin=MagicMock())
    assert result["intake_enabled"] is False
    assert result["worker_seen"] is None
    assert result["pending_messages"] is None
    factory.assert_not_called()
    redis.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [(AdminRole.viewer, 403), (AdminRole.admin_tenant, 200)])
@pytest.mark.parametrize("kind", ["message", "status", "notification"])
async def test_operations_require_admin_role(role, expected, kind):
    tenant_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "tenant_a", "A", "active", None)
    payload = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=role.value,
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    app.dependency_overrides[get_current_admin] = lambda: payload
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    try:
        with (
            patch(
                "app.core.middleware.TenantResolver.from_tenant_id_header",
                new=AsyncMock(return_value=tenant),
            ),
            patch(
                "app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/api/v1/whatsapp/operations/events?kind={kind}",
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
        assert response.status_code == expected
        if expected == 403:
            session.execute.assert_not_awaited()
        else:
            assert response.json()["events"] == []
            statement = session.execute.await_args.args[0]
            assert tenant_id in statement.compile().params.values()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_notification_details_are_masked_and_audited():
    tenant = TenantContext(uuid.uuid4(), "tenant_a", "A", "active", None)
    admin = MagicMock(sub=str(uuid.uuid4()))
    event_id, contact_id = uuid.uuid4(), uuid.uuid4()
    event = MagicMock(
        id=event_id,
        contact_id=contact_id,
        state="uncertain",
        provider_message_id=None,
        outcome_code="provider_unconfirmed",
        redacted_at=None,
    )
    event_result, phone_result = MagicMock(), MagicMock()
    event_result.scalar_one_or_none.return_value = event
    phone_result.scalar_one_or_none.return_value = "+212600123456"
    session = AsyncMock()
    session.execute.side_effect = [event_result, phone_result]
    session.add = MagicMock()
    session.__aenter__.return_value = session
    with patch.object(TenantContext, "db_session", return_value=session):
        detail = await event_detail(event_id, kind="notification", tenant=tenant, admin=admin)
    assert detail["recipient_masked"] == "***3456"
    assert detail["provider_message_id"] == "Non disponible"
    assert "+212600123456" not in str(detail)
    assert session.add.call_args.args[0].action == "notif_outbox_view"
    assert tenant.id in session.execute.await_args_list[0].args[0].compile().params.values()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_notification_details_are_not_disclosed():
    tenant = TenantContext(uuid.uuid4(), "tenant_a", "A", "active", None)
    event = MagicMock(redacted_at="expired")
    result = MagicMock()
    result.scalar_one_or_none.return_value = event
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    with patch.object(TenantContext, "db_session", return_value=session):
        with pytest.raises(HTTPException) as exc:
            await event_detail(uuid.uuid4(), kind="notification", tenant=tenant, admin=MagicMock())
    assert exc.value.status_code == 410
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_review_rejects_unknown_tenant_event():
    tenant = TenantContext(uuid.uuid4(), "tenant_a", "A", "active", None)
    event_id = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    with patch("app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session):
        with pytest.raises(HTTPException) as exc:
            await review_event(
                event_id,
                ReviewRequest(action="resolve"),
                kind="notification",
                tenant=tenant,
                admin=MagicMock(sub=str(uuid.uuid4())),
            )
    assert exc.value.status_code == 404
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("redacted,expected", [(True, None), (False, "a" * 64)])
async def test_review_clears_only_expired_resolved_message_fingerprint(redacted, expected):
    tenant = TenantContext(uuid.uuid4(), "tenant_a", "A", "active", None)
    event_id = uuid.uuid4()
    event = MagicMock(id=event_id, state="uncertain", redacted_at="expired" if redacted else None,
                      sender_fingerprint="a" * 64)
    result = MagicMock()
    result.scalar_one_or_none.return_value = event
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    session.add = MagicMock()
    with patch("app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session):
        await review_event(event_id, ReviewRequest(action="resolve"), kind="message",
                           tenant=tenant, admin=MagicMock(sub=str(uuid.uuid4())))
    assert event.sender_fingerprint == expected
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [(AdminRole.viewer, 403), (AdminRole.admin_tenant, 200)])
@pytest.mark.parametrize("kind", ["status", "notification"])
async def test_review_requires_admin_and_records_audit(role, expected, kind):
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    tenant = TenantContext(tenant_id, "tenant_a", "A", "active", None)
    payload = AdminTokenPayload(
        sub=str(uuid.uuid4()),
        role=role.value,
        tenant_id=str(tenant_id),
        exp=9999999999,
        iat=1700000000,
        jti=str(uuid.uuid4()),
        type="access",
    )
    app.dependency_overrides[get_current_admin] = lambda: payload
    event = MagicMock(id=event_id, state="uncertain")
    result = MagicMock()
    result.scalar_one_or_none.return_value = event
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    session.add = MagicMock()
    try:
        with (
            patch(
                "app.core.middleware.TenantResolver.from_tenant_id_header",
                new=AsyncMock(return_value=tenant),
            ),
            patch(
                "app.api.v1.whatsapp_operations.get_session_factory", return_value=lambda: session
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/whatsapp/operations/events/{event_id}/review?kind={kind}",
                    headers={"X-Tenant-ID": str(tenant_id)},
                    json={"action": "follow_up"},
                )
        assert response.status_code == expected
        if expected == 403:
            session.execute.assert_not_awaited()
        else:
            assert response.json()["state"] == "follow_up"
            audit = session.add.call_args.args[0]
            assert audit.tenant_slug == tenant.slug and audit.details["decision"] == "follow_up"
            assert audit.resource_type == (
                "notification_outbox" if kind == "notification" else "whatsapp_inbox_event"
            )
            assert tenant_id in session.execute.await_args.args[0].compile().params.values()
            session.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
