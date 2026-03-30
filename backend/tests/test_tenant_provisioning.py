"""Tests for TenantProvisioningService — atomic provisioning with rollback."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import DuplicateTenantError, TenantProvisioningError
from app.models.enums import TenantStatus
from app.services.tenant.provisioning import TenantProvisioningService

# --- Factories ---


def _make_tenant_create_data(**overrides) -> MagicMock:
    """Create a mock TenantCreate schema."""
    defaults = {
        "name": "CRI Rabat-Salé-Kénitra",
        "slug": "rabat",
        "region": "Rabat-Salé-Kénitra",
        "logo_url": None,
        "accent_color": None,
        "whatsapp_config": {"phone_number_id": "123456789", "access_token": "token"},
        "max_contacts": 20000,
        "max_messages_per_year": 100000,
        "max_admins": 10,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_tenant_orm(**overrides):
    """Create a mock Tenant ORM object."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "CRI Rabat-Salé-Kénitra",
        "slug": "rabat",
        "region": "Rabat-Salé-Kénitra",
        "status": TenantStatus.provisioning,
        "whatsapp_config": {"phone_number_id": "123456789"},
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


# --- Mock helpers ---


def _mock_session_factory(existing_tenant=None):
    """Create a mock session factory.

    Args:
        existing_tenant: If not None, the slug check query will
                         return this value (simulating duplicate).
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # For the slug check query: scalar_one_or_none
    mock_result = MagicMock()
    if existing_tenant:
        mock_result.scalar_one_or_none.return_value = existing_tenant
    else:
        mock_result.scalar_one_or_none.return_value = None

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory, mock_session


# --- Tests ---


class TestProvisionTenantSuccess:
    """Test the happy path: all steps complete successfully."""

    @pytest.mark.asyncio
    async def test_provision_tenant_success(self):
        """Full provisioning should create all resources and activate tenant."""
        data = _make_tenant_create_data()
        tenant_orm = _make_tenant_orm()

        mock_factory, mock_session = _mock_session_factory(existing_tenant=None)
        mock_redis = AsyncMock()
        mock_qdrant = AsyncMock()
        mock_minio = AsyncMock()
        mock_minio.bucket_exists = AsyncMock(return_value=False)

        # mock session.refresh to set the id
        async def fake_refresh(obj):
            obj.id = tenant_orm.id

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=mock_factory
            ),
            patch("app.services.tenant.provisioning.get_redis", return_value=mock_redis),
            patch("app.services.tenant.provisioning.get_qdrant", return_value=mock_qdrant),
            patch("app.services.tenant.provisioning.get_minio", return_value=mock_minio),
        ):
            service = TenantProvisioningService()
            result = await service.provision_tenant(data)

        # Tenant record was added to session
        mock_session.add.assert_called_once()

        # Schema was created (at least one execute call with CREATE SCHEMA)
        execute_calls = mock_session.execute.call_args_list
        sql_calls = [str(c[0][0]) for c in execute_calls]
        assert any("CREATE SCHEMA" in s for s in sql_calls)

        # Qdrant collection was created
        mock_qdrant.create_collection.assert_called_once()
        call_kwargs = mock_qdrant.create_collection.call_args
        assert "kb_rabat" in str(call_kwargs)

        # Redis phone mapping was set
        mock_redis.set.assert_called_once()
        redis_call = mock_redis.set.call_args
        assert "phone_mapping:123456789" in str(redis_call)

        # MinIO bucket was created
        mock_minio.make_bucket.assert_called_once_with("cri-rabat")

        # Tenant status should be active after provisioning
        assert result.status == TenantStatus.active


class TestProvisionDuplicateSlug:
    """Test that duplicate slugs are rejected."""

    @pytest.mark.asyncio
    async def test_provision_duplicate_slug_raises(self):
        """Existing slug should raise DuplicateTenantError."""
        data = _make_tenant_create_data(slug="existing")
        existing_id = uuid.uuid4()

        mock_factory, _mock_session = _mock_session_factory(existing_tenant=existing_id)

        with patch(
            "app.services.tenant.provisioning.get_session_factory",
            return_value=mock_factory,
        ):
            service = TenantProvisioningService()
            with pytest.raises(DuplicateTenantError, match="existing"):
                await service.provision_tenant(data)


class TestProvisionRollback:
    """Test rollback when a step fails."""

    @pytest.mark.asyncio
    async def test_provision_rollback_on_qdrant_failure(self):
        """If Qdrant fails, PG schema and DB record should be rolled back."""
        data = _make_tenant_create_data(whatsapp_config=None)
        tenant_orm = _make_tenant_orm()

        mock_factory, mock_session = _mock_session_factory(existing_tenant=None)
        mock_qdrant = AsyncMock()
        mock_qdrant.create_collection = AsyncMock(
            side_effect=RuntimeError("Qdrant connection refused")
        )

        # For rollback — need a second factory call for _drop_schema and _delete_tenant_record
        rollback_session = AsyncMock()
        rollback_session.__aenter__ = AsyncMock(return_value=rollback_session)
        rollback_session.__aexit__ = AsyncMock(return_value=False)
        rollback_session.execute = AsyncMock()
        rollback_session.commit = AsyncMock()

        call_count = 0
        original_mock_session = mock_session

        def factory_side_effect():
            nonlocal call_count
            call_count += 1
            # First call: _create_tenant_record, second: _create_schema
            # Third+: rollback calls
            if call_count <= 2:
                return original_mock_session
            return rollback_session

        mock_factory.side_effect = factory_side_effect
        mock_factory.return_value = None  # Disable default

        async def fake_refresh(obj):
            obj.id = tenant_orm.id

        original_mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=mock_factory
            ),
            patch("app.services.tenant.provisioning.get_qdrant", return_value=mock_qdrant),
            patch("app.services.tenant.provisioning.get_redis", return_value=AsyncMock()),
            patch("app.services.tenant.provisioning.get_minio", return_value=AsyncMock()),
        ):
            service = TenantProvisioningService()
            with pytest.raises(TenantProvisioningError, match="Qdrant connection refused"):
                await service.provision_tenant(data)

        # Verify rollback happened — schema drop and record delete
        rollback_calls = rollback_session.execute.call_args_list
        rollback_sql = [str(c[0][0]) for c in rollback_calls]
        assert any("DROP SCHEMA" in s for s in rollback_sql)


class TestDeprovisionTenant:
    """Test tenant deprovisioning."""

    @pytest.mark.asyncio
    async def test_deprovision_tenant(self):
        """Deprovisioning should clean up all resources."""
        tenant_orm = _make_tenant_orm(
            status=TenantStatus.active,
            whatsapp_config={"phone_number_id": "123456789"},
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tenant_orm
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)
        mock_redis = AsyncMock()
        mock_qdrant = AsyncMock()
        mock_minio = AsyncMock()
        mock_minio.bucket_exists = AsyncMock(return_value=True)

        # list_objects returns an async iterable (not a coroutine)
        class EmptyAsyncIter:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        mock_minio.list_objects = MagicMock(return_value=EmptyAsyncIter())

        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=mock_factory
            ),
            patch("app.services.tenant.provisioning.get_redis", return_value=mock_redis),
            patch("app.services.tenant.provisioning.get_qdrant", return_value=mock_qdrant),
            patch("app.services.tenant.provisioning.get_minio", return_value=mock_minio),
        ):
            service = TenantProvisioningService()
            await service.deprovision_tenant("rabat")

        # Qdrant collection deleted
        mock_qdrant.delete_collection.assert_called_once_with(collection_name="kb_rabat")

        # Redis phone mapping cleaned
        mock_redis.delete.assert_any_call("phone_mapping:123456789")

        # MinIO bucket removed
        mock_minio.remove_bucket.assert_called_once_with("cri-rabat")
