"""Tests for Notification API endpoints (/api/v1/notifications/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched TenantResolver for middleware bypass.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole, DossierStatut, Language, OptInStatus
from app.schemas.auth import AdminTokenPayload

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config={
        "phone_number_id": "123456",
        "access_token": "test-token",
    },
)


def _make_admin_payload(
    role: str = AdminRole.admin_tenant.value,
    **overrides,
) -> AdminTokenPayload:
    defaults = {
        "sub": str(uuid.uuid4()),
        "role": role,
        "tenant_id": str(TEST_TENANT.id),
        "exp": 9999999999,
        "iat": 1700000000,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    defaults.update(overrides)
    return AdminTokenPayload(**defaults)


def _make_audit_log_orm(
    action: str = "notification_sent",
    event_type: str = "decision_finale",
    **detail_overrides,
) -> MagicMock:
    """Create a mock AuditLog ORM object for notification history."""
    details = {
        "event_type": event_type,
        "contact_id": str(uuid.uuid4()),
        "template": "dossier_decision_finale",
        "wamid": "wamid.abc123",
        "numero": "2024-CRI-0001",
    }
    details.update(detail_overrides)
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.tenant_slug = TEST_TENANT.slug
    mock.action = action
    mock.resource_type = "notification"
    mock.resource_id = str(uuid.uuid4())
    mock.details = details
    mock.created_at = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    return mock


def _make_contact_orm(
    contact_id: uuid.UUID | None = None,
    **overrides,
) -> MagicMock:
    defaults = {
        "id": contact_id or uuid.uuid4(),
        "phone": "+212612345678",
        "name": "Mohammed Test",
        "language": Language.fr,
        "opt_in_status": OptInStatus.pending,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_dossier_orm(
    dossier_id: uuid.UUID | None = None,
    **overrides,
) -> MagicMock:
    defaults = {
        "id": dossier_id or uuid.uuid4(),
        "numero": "2024-CRI-0001",
        "statut": DossierStatut.en_cours,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_tenant_db_session(
    *,
    scalar_one_or_none=None,
    execute_results=None,
):
    """Create a mock for tenant.db_session() async context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    if execute_results is not None:
        mock_session.execute = AsyncMock(side_effect=execute_results)
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = scalar_one_or_none
        mock_session.execute = AsyncMock(return_value=mock_result)

    return mock_session


def _mock_public_session(*, execute_results=None):
    """Create a mock for get_session_factory() (public schema queries).

    get_session_factory() returns a callable factory.
    factory() returns an async context manager (the session).
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(side_effect=execute_results or [])
    mock_session.commit = AsyncMock()

    # factory() → async context manager (mock_session)
    mock_factory_callable = MagicMock(return_value=mock_session)
    return mock_factory_callable, mock_session


def _setup_overrides(role: str = AdminRole.admin_tenant.value) -> AdminTokenPayload:
    payload = _make_admin_payload(role=role)
    app.dependency_overrides[get_current_admin] = lambda: payload
    return payload


def _clear_overrides():
    app.dependency_overrides.pop(get_current_admin, None)


def _headers() -> dict:
    return {
        "Authorization": "Bearer mock-token",
        "X-Tenant-ID": str(TEST_TENANT.id),
    }


# ---------------------------------------------------------------------------
# GET /notifications — History
# ---------------------------------------------------------------------------


class TestListNotificationHistory:
    @pytest.mark.asyncio
    async def test_list_history_requires_auth(self):
        """GET /notifications returns 401 without auth token."""
        with patch("app.core.middleware.TenantResolver") as MockResolver:
            MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Send tenant header but no auth token
                response = await client.get(
                    "/api/v1/notifications",
                    headers={"X-Tenant-ID": str(TEST_TENANT.id)},
                )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_history_viewer_forbidden(self):
        """Viewer role cannot access notification history."""
        _setup_overrides(role=AdminRole.viewer.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_history_paginated(self):
        """GET /notifications returns paginated notification history."""
        _setup_overrides(role=AdminRole.supervisor.value)

        logs = [_make_audit_log_orm() for _ in range(2)]

        # Three execute calls: SET search_path, count, data
        set_path_result = MagicMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = logs
        data_result.scalars.return_value = mock_scalars

        mock_factory, mock_session = _mock_public_session(
            execute_results=[set_path_result, count_result, data_result],
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.notifications.get_session_factory",
                    return_value=mock_factory,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications?page=1&page_size=10",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 10

    @pytest.mark.asyncio
    async def test_list_history_filter_by_status(self):
        """GET /notifications?status=sent filters to sent notifications."""
        _setup_overrides(role=AdminRole.supervisor.value)

        logs = [_make_audit_log_orm(action="notification_sent")]

        set_path_result = MagicMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = logs
        data_result.scalars.return_value = mock_scalars

        mock_factory, _ = _mock_public_session(
            execute_results=[set_path_result, count_result, data_result],
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.notifications.get_session_factory",
                    return_value=mock_factory,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications?status=sent",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        for item in data["items"]:
            assert item["status"] == "sent"


# ---------------------------------------------------------------------------
# GET /notifications/stats — Stats
# ---------------------------------------------------------------------------


class TestGetNotificationStats:
    @pytest.mark.asyncio
    async def test_stats_default(self):
        """GET /notifications/stats returns aggregated statistics."""
        _setup_overrides(role=AdminRole.supervisor.value)

        # SET search_path, action count, event_type count
        set_path_result = MagicMock()

        action_result = MagicMock()
        action_result.__iter__ = MagicMock(
            return_value=iter([
                ("notification_sent", 10),
                ("notification_skipped", 3),
                ("notification_failed", 1),
            ])
        )

        event_result = MagicMock()
        event_result.__iter__ = MagicMock(
            return_value=iter([
                ("decision_finale", 8),
                ("status_update", 6),
            ])
        )

        mock_factory, _ = _mock_public_session(
            execute_results=[set_path_result, action_result, event_result],
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.notifications.get_session_factory",
                    return_value=mock_factory,
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total_sent"] == 10
        assert data["total_skipped"] == 3
        assert data["total_failed"] == 1
        assert data["period_days"] == 30
        assert data["by_event_type"]["decision_finale"] == 8

    @pytest.mark.asyncio
    async def test_stats_viewer_forbidden(self):
        """Viewer role cannot access notification stats."""
        _setup_overrides(role=AdminRole.viewer.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications/stats",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /notifications/send — Manual send
# ---------------------------------------------------------------------------


class TestSendManualNotification:
    @pytest.mark.asyncio
    async def test_send_success(self):
        """Manual send succeeds with valid contact and dossier."""
        payload = _setup_overrides(role=AdminRole.admin_tenant.value)

        contact_id = uuid.uuid4()
        dossier_id = uuid.uuid4()
        contact = _make_contact_orm(contact_id=contact_id)
        dossier = _make_dossier_orm(dossier_id=dossier_id)

        # Two db_session calls: contact load, dossier load
        contact_result = MagicMock()
        contact_result.scalar_one_or_none.return_value = contact
        dossier_result = MagicMock()
        dossier_result.scalar_one_or_none.return_value = dossier

        mock_session = _mock_tenant_db_session(
            execute_results=[contact_result, dossier_result],
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session
                ),
                patch(
                    "app.api.v1.notifications.WhatsAppSenderService"
                ) as MockSender,
                patch(
                    "app.api.v1.notifications.get_audit_service"
                ) as mock_get_audit,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_sender_inst = MockSender.return_value
                mock_sender_inst.send_template = AsyncMock(
                    return_value="wamid.test123"
                )
                mock_audit = MagicMock()
                mock_audit.log_action = AsyncMock()
                mock_get_audit.return_value = mock_audit

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/notifications/send",
                        headers=_headers(),
                        json={
                            "contact_id": str(contact_id),
                            "dossier_id": str(dossier_id),
                            "event_type": "decision_finale",
                        },
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["wamid"] == "wamid.test123"

    @pytest.mark.asyncio
    async def test_send_contact_not_found(self):
        """Manual send returns 404 when contact does not exist."""
        _setup_overrides(role=AdminRole.admin_tenant.value)

        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/notifications/send",
                        headers=_headers(),
                        json={
                            "contact_id": str(uuid.uuid4()),
                            "dossier_id": str(uuid.uuid4()),
                            "event_type": "status_update",
                        },
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_opted_out(self):
        """Manual send skips when contact has opted out."""
        _setup_overrides(role=AdminRole.admin_tenant.value)

        contact_id = uuid.uuid4()
        dossier_id = uuid.uuid4()
        contact = _make_contact_orm(
            contact_id=contact_id,
            opt_in_status=OptInStatus.opted_out,
        )
        dossier = _make_dossier_orm(dossier_id=dossier_id)

        contact_result = MagicMock()
        contact_result.scalar_one_or_none.return_value = contact
        dossier_result = MagicMock()
        dossier_result.scalar_one_or_none.return_value = dossier

        mock_session = _mock_tenant_db_session(
            execute_results=[contact_result, dossier_result],
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(
                    TenantContext, "db_session", return_value=mock_session
                ),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/notifications/send",
                        headers=_headers(),
                        json={
                            "contact_id": str(contact_id),
                            "dossier_id": str(dossier_id),
                            "event_type": "decision_finale",
                        },
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["reason"] == "opted_out"

    @pytest.mark.asyncio
    async def test_send_supervisor_forbidden(self):
        """Supervisor role cannot send manual notifications."""
        _setup_overrides(role=AdminRole.supervisor.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/notifications/send",
                        headers=_headers(),
                        json={
                            "contact_id": str(uuid.uuid4()),
                            "dossier_id": str(uuid.uuid4()),
                            "event_type": "status_update",
                        },
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_send_invalid_event_type(self):
        """Manual send returns 422 for invalid event_type."""
        _setup_overrides(role=AdminRole.admin_tenant.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/notifications/send",
                        headers=_headers(),
                        json={
                            "contact_id": str(uuid.uuid4()),
                            "dossier_id": str(uuid.uuid4()),
                            "event_type": "invalid_type",
                        },
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /notifications/templates — Templates
# ---------------------------------------------------------------------------


class TestListTemplates:
    @pytest.mark.asyncio
    async def test_list_templates(self):
        """GET /templates returns all 4 notification templates."""
        _setup_overrides(role=AdminRole.supervisor.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/notifications/templates",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 4
        event_types = {t["event_type"] for t in data}
        assert event_types == {
            "decision_finale",
            "complement_request",
            "status_update",
            "dossier_incomplet",
        }
        for t in data:
            assert "template_name" in t
            assert "description" in t
            assert "priority" in t


# ---------------------------------------------------------------------------
# PUT /notifications/templates/{event_type} — Update template
# ---------------------------------------------------------------------------


class TestUpdateTemplate:
    @pytest.mark.asyncio
    async def test_update_template_success(self):
        """PUT /templates/{event_type} updates the template name."""
        _setup_overrides(role=AdminRole.admin_tenant.value)

        # Mock public session for Tenant update
        mock_tenant_row = MagicMock()
        mock_tenant_row.whatsapp_config = {
            "phone_number_id": "123",
            "access_token": "tok",
        }

        set_path_result = MagicMock()
        select_result = MagicMock()
        select_result.scalar_one.return_value = mock_tenant_row

        mock_factory, _ = _mock_public_session(
            execute_results=[set_path_result, select_result],
        )

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.notifications.get_session_factory",
                    return_value=mock_factory,
                ),
                patch(
                    "app.api.v1.notifications.get_redis",
                    return_value=mock_redis,
                ),
                patch(
                    "app.api.v1.notifications.get_audit_service"
                ) as mock_get_audit,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                mock_audit = MagicMock()
                mock_audit.log_action = AsyncMock()
                mock_get_audit.return_value = mock_audit

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.put(
                        "/api/v1/notifications/templates/decision_finale",
                        headers=_headers(),
                        json={"template_name": "custom_decision_template"},
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "decision_finale"
        assert data["template_name"] == "custom_decision_template"

    @pytest.mark.asyncio
    async def test_update_template_invalid_event_type(self):
        """PUT /templates/invalid returns 422."""
        _setup_overrides(role=AdminRole.admin_tenant.value)
        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(
                    return_value=TEST_TENANT
                )
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.put(
                        "/api/v1/notifications/templates/invalid_event",
                        headers=_headers(),
                        json={"template_name": "some_template"},
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422
