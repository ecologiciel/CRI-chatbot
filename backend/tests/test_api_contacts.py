"""Tests for Contacts API endpoints (/api/v1/contacts/).

Uses httpx AsyncClient with dependency overrides for RBAC
and patched TenantResolver for middleware bypass.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import get_current_admin
from app.core.tenant import TenantContext
from app.main import app
from app.models.enums import AdminRole, ContactSource, Language, OptInStatus
from app.schemas.auth import AdminTokenPayload


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_admin_payload(
    role: str = AdminRole.admin_tenant.value, **overrides
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


def _make_contact_orm(contact_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock Contact ORM object."""
    defaults = {
        "id": contact_id or uuid.uuid4(),
        "phone": "+212612345678",
        "name": "Mohammed Test",
        "language": Language.fr,
        "cin": "AB12345",
        "opt_in_status": OptInStatus.pending,
        "tags": ["investisseur"],
        "source": ContactSource.whatsapp,
        "metadata_": {},
        "created_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "conversations": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _mock_tenant_db_session(
    *,
    scalar_one_or_none=None,
    scalar_one=None,
    scalars_all=None,
    execute_results=None,
):
    """Create a mock for tenant.db_session() async context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    if execute_results is not None:
        mock_session.execute = AsyncMock(side_effect=execute_results)
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = scalar_one_or_none
        mock_result.scalar_one.return_value = scalar_one if scalar_one is not None else (scalar_one_or_none if scalar_one_or_none is not None else 0)

        if scalars_all is not None:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = scalars_all
            mock_result.scalars.return_value = mock_scalars

        mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = AsyncMock()

    return mock_session


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
# List contacts
# ---------------------------------------------------------------------------


class TestListContacts:
    @pytest.mark.asyncio
    async def test_list_success(self):
        """GET /contacts returns paginated list."""
        _setup_overrides(role=AdminRole.supervisor.value)

        contacts = [_make_contact_orm() for _ in range(3)]
        # Two execute calls: count then data
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3

        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = contacts
        data_result.scalars.return_value = mock_scalars

        mock_session = _mock_tenant_db_session(execute_results=[count_result, data_result])

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/contacts?page=1&page_size=20",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_with_search(self):
        """GET /contacts?search=Mohammed filters results."""
        _setup_overrides(role=AdminRole.supervisor.value)

        contacts = [_make_contact_orm(name="Mohammed Test")]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = contacts
        data_result.scalars.return_value = mock_scalars

        mock_session = _mock_tenant_db_session(execute_results=[count_result, data_result])

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/contacts?search=Mohammed",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_list_rbac_viewer_denied(self):
        """GET /contacts with viewer role returns 403."""
        _setup_overrides(role=AdminRole.viewer.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/contacts",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Create contact
# ---------------------------------------------------------------------------


class TestCreateContact:
    @pytest.mark.asyncio
    async def test_create_success(self):
        """POST /contacts creates a new contact."""
        _setup_overrides()

        contact_orm = _make_contact_orm(phone="+212698765432", source=ContactSource.manual)

        # Two execute calls: check uniqueness, then insert
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = None  # no duplicate

        mock_session = _mock_tenant_db_session(execute_results=[check_result])

        async def fake_refresh(obj):
            obj.id = contact_orm.id
            obj.phone = obj.phone
            obj.name = getattr(obj, "name", None)
            obj.language = getattr(obj, "language", Language.fr)
            obj.cin = getattr(obj, "cin", None)
            obj.opt_in_status = getattr(obj, "opt_in_status", OptInStatus.pending)
            obj.tags = getattr(obj, "tags", [])
            obj.source = getattr(obj, "source", ContactSource.manual)
            obj.created_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
            obj.updated_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts",
                        json={
                            "phone": "+212698765432",
                            "name": "Nouveau Contact",
                            "language": "fr",
                            "source": "manual",
                        },
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 201
        data = response.json()
        assert data["phone"] == "+212698765432"

    @pytest.mark.asyncio
    async def test_create_invalid_phone(self):
        """POST /contacts with invalid phone returns 422."""
        _setup_overrides()

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts",
                        json={"phone": "0612345", "name": "Bad Phone"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_rbac_supervisor_denied(self):
        """POST /contacts with supervisor role returns 403."""
        _setup_overrides(role=AdminRole.supervisor.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts",
                        json={"phone": "+212612345678"},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Delete contact
# ---------------------------------------------------------------------------


class TestDeleteContact:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        """DELETE /contacts/{id} returns 204."""
        _setup_overrides()

        contact_orm = _make_contact_orm()
        mock_session = _mock_tenant_db_session(scalar_one_or_none=contact_orm)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.delete(
                        f"/api/v1/contacts/{contact_orm.id}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE /contacts/{id} with unknown ID returns 404."""
        _setup_overrides()

        mock_session = _mock_tenant_db_session(scalar_one_or_none=None)

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch.object(TenantContext, "db_session", return_value=mock_session),
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.delete(
                        f"/api/v1/contacts/{uuid.uuid4()}",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Import contacts
# ---------------------------------------------------------------------------


class TestImportContacts:
    @pytest.mark.asyncio
    async def test_import_csv_success(self):
        """POST /contacts/import with valid CSV returns import results."""
        _setup_overrides()

        csv_content = b"phone,name,language\n+212612345678,Test User,fr\n+212698765432,User2,ar\n"

        # Mock the import service
        from app.services.contact.import_export import ImportResult

        mock_result = ImportResult(created=2, skipped=0, errors=[])

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.contacts.get_import_export_service"
                ) as mock_ie_svc,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                mock_service = MagicMock()
                mock_service.import_contacts = AsyncMock(return_value=mock_result)
                mock_ie_svc.return_value = mock_service

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts/import",
                        files={"file": ("contacts.csv", csv_content, "text/csv")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 2
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_import_bad_extension(self):
        """POST /contacts/import with .txt returns 422."""
        _setup_overrides()

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts/import",
                        files={"file": ("data.txt", b"some text", "text/plain")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_import_rbac_supervisor_denied(self):
        """POST /contacts/import with supervisor role returns 403."""
        _setup_overrides(role=AdminRole.supervisor.value)

        try:
            with patch("app.core.middleware.TenantResolver") as MockResolver:
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/contacts/import",
                        files={"file": ("c.csv", b"phone\n+212600000000\n", "text/csv")},
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Export contacts
# ---------------------------------------------------------------------------


class TestExportContacts:
    @pytest.mark.asyncio
    async def test_export_csv(self):
        """GET /contacts/export?format=csv returns CSV content."""
        _setup_overrides(role=AdminRole.supervisor.value)

        mock_service = MagicMock()
        mock_service.export_to_csv = AsyncMock(
            return_value="phone,name\n+212612345678,Test\n"
        )

        try:
            with (
                patch("app.core.middleware.TenantResolver") as MockResolver,
                patch(
                    "app.api.v1.contacts.get_import_export_service"
                ) as mock_ie_svc,
            ):
                MockResolver.from_tenant_id_header = AsyncMock(return_value=TEST_TENANT)
                mock_ie_svc.return_value = mock_service

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/contacts/export?format=csv",
                        headers=_headers(),
                    )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
