"""Tests for TenantProvisioningService — atomic provisioning with rollback."""

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.exceptions import (
    DuplicateResourceError,
    DuplicateTenantError,
    TenantProvisioningError,
)
from app.models.enums import TenantStatus
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
from app.schemas.tenant import TenantCreate, WhatsAppConfig
from app.services.tenant.provisioning import TenantProvisioningService


@pytest.fixture(autouse=True)
def mock_lifecycle_lock():
    """These unit tests isolate their existing mocks from database locks."""

    @asynccontextmanager
    async def unlocked(_value):
        yield

    with (
        patch("app.services.tenant.provisioning.protect_removal", unlocked),
        patch("app.services.tenant.provisioning._assert_template_compatible", new=AsyncMock()),
    ):
        yield


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
    async def test_duplicate_whatsapp_identifier_is_a_conflict(self):
        factory, session = _mock_session_factory()
        session.commit.side_effect = IntegrityError(
            "INSERT", {}, Exception("duplicate key uq_tenants_whatsapp_phone")
        )
        with (
            patch("app.services.tenant.provisioning.get_session_factory", return_value=factory),
            pytest.raises(DuplicateResourceError),
        ):
            await TenantProvisioningService()._create_tenant_record(_make_tenant_create_data())
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_real_whatsapp_config_is_persisted_as_plain_dict(self):
        config = WhatsAppConfig(
            phone_number_id=" 123456789 ", access_token="secret", verify_token="verify"
        )
        data = TenantCreate(
            name="Institution", slug="institution", region="Maroc", whatsapp_config=config
        )
        factory, session = _mock_session_factory()
        with patch("app.services.tenant.provisioning.get_session_factory", return_value=factory):
            await TenantProvisioningService()._create_tenant_record(data)
        tenant = session.add.call_args.args[0]
        assert tenant.whatsapp_config["phone_number_id"] == "123456789"
        assert isinstance(tenant.whatsapp_config, dict)

    @pytest.mark.asyncio
    async def test_legacy_redis_mapping_does_not_store_whatsapp_credentials(self):
        tenant = _make_tenant_orm(
            whatsapp_config={"phone_number_id": "123", "access_token": "secret"}
        )
        redis = AsyncMock()
        with patch("app.services.tenant.provisioning.get_redis", return_value=redis):
            await TenantProvisioningService()._create_redis_mapping(tenant, "123")
        mapping = json.loads(redis.set.await_args.args[1])
        assert "whatsapp_config" not in mapping
        assert "secret" not in str(mapping)

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

        # Provisioning persists both the tenant and its encryption key.
        added = [call.args[0] for call in mock_session.add.call_args_list]
        assert sum(isinstance(item, Tenant) for item in added) == 1
        expected_keys = int(bool(get_settings().kms_master_key))
        assert sum(isinstance(item, TenantKey) for item in added) == expected_keys

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
    """Test compensation and retention when a step fails."""

    @pytest.mark.asyncio
    async def test_provision_rollback_on_qdrant_failure(self):
        """If Qdrant fails, compensate the schema but keep an inactive record."""
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
            with patch.object(
                service, "_deactivate_failed_provisioning", new_callable=AsyncMock
            ) as deactivate:
                with pytest.raises(TenantProvisioningError, match="inactive tenant retained"):
                    await service.provision_tenant(data)
            deactivate.assert_awaited_once()

        # Verify the schema compensation while retaining the tenant record.
        rollback_calls = rollback_session.execute.call_args_list
        rollback_sql = [str(c[0][0]) for c in rollback_calls]
        assert any("DROP SCHEMA" in s for s in rollback_sql)
        assert not any("DELETE FROM public.tenants" in s for s in rollback_sql)

    @pytest.mark.asyncio
    async def test_failed_compensation_keeps_record_and_reports_step(self):
        data = _make_tenant_create_data(whatsapp_config=None)
        tenant = _make_tenant_orm()
        service = TenantProvisioningService()
        with (
            patch.object(service, "_create_tenant_record", new=AsyncMock(return_value=tenant)),
            patch.object(service, "_create_schema", new=AsyncMock()),
            patch.object(
                service,
                "_create_qdrant_collection",
                new=AsyncMock(side_effect=RuntimeError("lost response")),
            ),
            patch.object(service, "_deactivate_failed_provisioning", new=AsyncMock()) as deactivate,
            patch.object(
                service, "_drop_schema", new=AsyncMock(side_effect=RuntimeError("db unavailable"))
            ),
        ):
            with pytest.raises(TenantProvisioningError) as error:
                await service.provision_tenant(data)
        deactivate.assert_awaited_once_with(tenant.id, data.slug)
        assert error.value.details == {
            "cleanup_failures": ["pg_schema"],
            "tenant_id": str(tenant.id),
        }
        assert "lost response" not in str(error.value)

    @pytest.mark.asyncio
    async def test_unconfirmed_deactivation_stops_compensation(self):
        data = _make_tenant_create_data(whatsapp_config=None)
        tenant = _make_tenant_orm()
        service = TenantProvisioningService()
        with (
            patch.object(service, "_create_tenant_record", new=AsyncMock(return_value=tenant)),
            patch.object(service, "_create_schema", new=AsyncMock()),
            patch.object(
                service,
                "_create_qdrant_collection",
                new=AsyncMock(side_effect=RuntimeError("lost response")),
            ),
            patch.object(
                service,
                "_deactivate_failed_provisioning",
                new=AsyncMock(side_effect=RuntimeError("db unavailable")),
            ),
            patch.object(service, "_drop_schema", new=AsyncMock()) as drop,
        ):
            with pytest.raises(TenantProvisioningError, match="cleanup not attempted"):
                await service.provision_tenant(data)
        drop.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_busy_lifecycle_lock_preserves_resources_for_review(self):
        data = _make_tenant_create_data(whatsapp_config=None)
        tenant = _make_tenant_orm()
        service = TenantProvisioningService()

        @asynccontextmanager
        async def busy(_slug):
            raise RuntimeError("busy")
            yield

        with (
            patch.object(service, "_create_tenant_record", new=AsyncMock(return_value=tenant)),
            patch.object(service, "_create_schema", new=AsyncMock()),
            patch.object(
                service,
                "_create_qdrant_collection",
                new=AsyncMock(side_effect=RuntimeError("lost response")),
            ),
            patch.object(service, "_deactivate_failed_provisioning", new=AsyncMock()),
            patch.object(service, "_drop_schema", new=AsyncMock()) as drop,
            patch("app.services.tenant.provisioning.protect_removal", busy),
        ):
            with pytest.raises(TenantProvisioningError) as error:
                await service.provision_tenant(data)
        assert error.value.details["cleanup_failures"] == ["lifecycle_lock"]
        drop.assert_not_awaited()


class TestDeprovisionTenant:
    """Test tenant deprovisioning."""

    @pytest.mark.asyncio
    async def test_empty_minio_page_does_not_prevent_bucket_removal(self):
        async def objects():
            yield None  # miniopy_async emits this for an empty page

        minio = AsyncMock()
        minio.bucket_exists.return_value = True
        minio.list_objects = MagicMock(return_value=objects())
        with patch("app.services.tenant.provisioning.get_minio", return_value=minio):
            await TenantProvisioningService()._empty_and_remove_bucket("temporary")
        minio.remove_object.assert_not_awaited()
        minio.remove_bucket.assert_awaited_once_with("cri-temporary")

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_tenant_record_and_reports_error(self):
        tenant = _make_tenant_orm(status=TenantStatus.active, whatsapp_config=None)
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.return_value = MagicMock(scalar_one_or_none=lambda: tenant)
        service = TenantProvisioningService()
        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=lambda: session
            ),
            patch("app.services.tenant.provisioning.get_redis", return_value=AsyncMock()),
            patch(
                "app.services.tenant.provisioning._clear_tenant_redis_keys", new_callable=AsyncMock
            ),
            patch.object(service, "_empty_and_remove_bucket", side_effect=RuntimeError("storage")),
            patch.object(service, "_delete_qdrant_collection", new_callable=AsyncMock),
            patch.object(service, "_drop_schema", new_callable=AsyncMock),
            patch("app.services.tenant.provisioning.get_settings") as settings,
        ):
            settings.return_value.kms_master_key = ""
            with pytest.raises(TenantProvisioningError, match="minio"):
                await service.deprovision_tenant("rabat")
        assert not any(
            "DELETE FROM" in str(call.args[0]) for call in session.execute.await_args_list
        )

    @pytest.mark.asyncio
    async def test_deactivation_failure_stops_before_removing_resources(self):
        tenant = _make_tenant_orm(status=TenantStatus.active, whatsapp_config=None)
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.side_effect = [
            MagicMock(scalar_one_or_none=lambda: tenant),
            RuntimeError("database unavailable"),
        ]
        service = TenantProvisioningService()
        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=lambda: session
            ),
            patch.object(
                service, "_empty_and_remove_bucket", new_callable=AsyncMock
            ) as remove_bucket,
            patch.object(service, "_drop_schema", new_callable=AsyncMock) as drop_schema,
        ):
            with pytest.raises(TenantProvisioningError, match="resources were not removed"):
                await service.deprovision_tenant("rabat")
        remove_bucket.assert_not_awaited()
        drop_schema.assert_not_awaited()
        session.commit.assert_not_awaited()

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
            patch(
                "app.services.tenant.provisioning._clear_tenant_redis_keys", new_callable=AsyncMock
            ),
            patch("app.services.tenant.provisioning.get_qdrant", return_value=mock_qdrant),
            patch("app.services.tenant.provisioning.get_minio", return_value=mock_minio),
        ):
            service = TenantProvisioningService()
            await service.deprovision_tenant("rabat")

        # All tenant-bound accounts are disabled before deleting resources.
        statements = [str(call.args[0]) for call in mock_session.execute.await_args_list]
        assert any("UPDATE public.admins" in statement for statement in statements)
        assert tenant_orm.status == TenantStatus.inactive

        # Qdrant collection deleted
        mock_qdrant.delete_collection.assert_called_once_with(collection_name="kb_rabat")

        # Redis phone mapping cleaned
        mock_redis.delete.assert_any_call("phone_mapping:123456789")

        # MinIO bucket removed
        mock_minio.remove_bucket.assert_called_once_with("cri-rabat")


class TestTenantRedisCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_is_confined_to_exact_tenant_prefix(self):
        from app.services.tenant.provisioning import _clear_tenant_redis_keys

        class FakeRedis:
            def __init__(self):
                self.keys = {
                    "onssa:web_session:a",
                    "onssa:rl:web:a",
                    "onssatest:web_session:b",
                    "auth:session:x",
                }

            async def scan_iter(self, match, count):
                assert match == "onssa:*"
                for key in list(self.keys):
                    if key.startswith("onssa:"):
                        yield key

            async def delete(self, *keys):
                self.keys.difference_update(keys)
                return len(keys)

        redis = FakeRedis()
        assert await _clear_tenant_redis_keys(redis, "onssa") == 2
        assert redis.keys == {"onssatest:web_session:b", "auth:session:x"}

    @pytest.mark.asyncio
    async def test_cleanup_rejects_glob_metacharacters(self):
        from app.services.tenant.provisioning import _clear_tenant_redis_keys

        with pytest.raises(ValueError, match="Invalid tenant slug"):
            await _clear_tenant_redis_keys(AsyncMock(), "onssa*")

    @pytest.mark.asyncio
    async def test_cleanup_fails_if_new_keys_keep_appearing(self):
        from app.services.tenant.provisioning import _clear_tenant_redis_keys

        class BusyRedis:
            async def scan_iter(self, match, count):
                yield "onssa:session:recreated"

            async def delete(self, *keys):
                return len(keys)

        with pytest.raises(RuntimeError, match="bounded cleanup"):
            await _clear_tenant_redis_keys(BusyRedis(), "onssa")

    @pytest.mark.asyncio
    async def test_cleanup_failure_preserves_tenant_record(self):
        tenant = _make_tenant_orm(status=TenantStatus.active, whatsapp_config=None)
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.return_value = MagicMock(scalar_one_or_none=lambda: tenant)
        service = TenantProvisioningService()
        with (
            patch(
                "app.services.tenant.provisioning.get_session_factory", return_value=lambda: session
            ),
            patch("app.services.tenant.provisioning.get_redis", return_value=AsyncMock()),
            patch(
                "app.services.tenant.provisioning._clear_tenant_redis_keys",
                AsyncMock(side_effect=RuntimeError("busy")),
            ),
            patch.object(service, "_empty_and_remove_bucket", new_callable=AsyncMock),
            patch.object(service, "_delete_qdrant_collection", new_callable=AsyncMock),
            patch.object(service, "_drop_schema", new_callable=AsyncMock),
            patch("app.services.tenant.provisioning.get_settings") as settings,
        ):
            settings.return_value.kms_master_key = ""
            with pytest.raises(TenantProvisioningError, match="redis"):
                await service.deprovision_tenant("rabat")
        assert not any(
            "DELETE FROM public.tenants" in str(call.args[0])
            for call in session.execute.await_args_list
        )
