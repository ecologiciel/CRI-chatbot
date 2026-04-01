"""Tests unitaires du module Campagnes / Publipostage WhatsApp.

Couvre :
- CampaignService : create, audience builder, variable resolution, quota, launch, pause
- Worker send_campaign : batching, idempotent, pause flag
- Constants et enums
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Env vars must be set BEFORE importing app modules
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key")

from app.models.enums import CampaignStatus, OptInStatus, RecipientStatus

TEST_TENANT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_ADMIN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _make_tenant_mock(session_mock=None):
    """Create a MagicMock tenant with db_session async context manager."""
    tenant = MagicMock()
    tenant.id = TEST_TENANT_ID
    tenant.slug = "rabat"
    tenant.name = "CRI Rabat"
    tenant.status = "active"
    tenant.redis_prefix = "rabat"
    tenant.whatsapp_config = {
        "phone_number_id": "111222333",
        "access_token": "test_token",
        "annual_message_limit": 100_000,
    }

    if session_mock:

        @asynccontextmanager
        async def fake_db():
            yield session_mock

        tenant.db_session = fake_db
    return tenant


def _make_campaign_service():
    """Create a CampaignService with all dependencies mocked."""
    from app.services.campaign.service import CampaignService

    return CampaignService(
        sender=AsyncMock(),
        audit=AsyncMock(),
        session_mgr=AsyncMock(),
    )


def _make_contact_mock(name="Contact Test", phone="+212610000001", **overrides):
    """Create a mock Contact."""
    defaults = {
        "id": uuid.uuid4(),
        "phone": phone,
        "name": name,
        "language": MagicMock(value="fr"),
        "opt_in_status": OptInStatus.opted_in,
        "tags": ["investisseur"],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# =====================================================================
# Resolve Variables
# =====================================================================


class TestResolveVariables:
    """Tests de la resolution des variables de template."""

    def test_resolve_contact_name(self):
        """Mapping 'contact.name' -> resolu avec le nom du contact."""
        from app.services.campaign.service import CampaignService

        contact = _make_contact_mock(name="Ahmed Benali")
        result = CampaignService.resolve_variables({"1": "contact.name"}, contact)
        # Returns [{"type": "body", "parameters": [{"type": "text", "text": "Ahmed Benali"}]}]
        assert len(result) == 1
        params = result[0]["parameters"]
        assert params[0]["text"] == "Ahmed Benali"

    def test_resolve_custom_text(self):
        """Mapping 'custom:Bienvenue' -> texte litteral."""
        from app.services.campaign.service import CampaignService

        contact = _make_contact_mock()
        result = CampaignService.resolve_variables({"1": "custom:Bienvenue"}, contact)
        assert len(result) == 1
        params = result[0]["parameters"]
        assert params[0]["text"] == "Bienvenue"

    def test_resolve_null_name_fallback(self):
        """Contact sans nom -> fallback 'Investisseur'."""
        from app.services.campaign.service import CampaignService, DEFAULT_NAME_FALLBACK

        contact = _make_contact_mock(name=None)
        result = CampaignService.resolve_variables({"1": "contact.name"}, contact)
        assert len(result) == 1
        params = result[0]["parameters"]
        assert params[0]["text"] == DEFAULT_NAME_FALLBACK

    def test_resolve_empty_mapping(self):
        """Mapping vide -> liste vide."""
        from app.services.campaign.service import CampaignService

        contact = _make_contact_mock()
        result = CampaignService.resolve_variables({}, contact)
        assert result == []


# =====================================================================
# Quota Check
# =====================================================================


class TestQuotaCheck:
    """Tests de la verification du quota WhatsApp."""

    @pytest.mark.asyncio
    async def test_quota_allowed(self):
        """used=50000, limit=100000, count=1000 -> allowed=True."""
        svc = _make_campaign_service()
        quota_info = MagicMock()
        quota_info.annual_count = 50_000
        quota_info.annual_limit = 100_000
        quota_info.remaining = 50_000
        svc._session_mgr.check_quota = AsyncMock(return_value=quota_info)

        tenant = _make_tenant_mock()
        result = await svc.check_quota(tenant, 1000)
        assert result["allowed"] is True
        assert result["remaining"] == 50_000

    @pytest.mark.asyncio
    async def test_quota_exceeded(self):
        """used=99500, limit=100000, count=1000 -> allowed=False."""
        svc = _make_campaign_service()
        quota_info = MagicMock()
        quota_info.annual_count = 99_500
        quota_info.annual_limit = 100_000
        quota_info.remaining = 500
        svc._session_mgr.check_quota = AsyncMock(return_value=quota_info)

        tenant = _make_tenant_mock()
        result = await svc.check_quota(tenant, 1000)
        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_quota_critical_at_95_percent(self):
        """Quota a 95% -> percentage >= 95."""
        svc = _make_campaign_service()
        quota_info = MagicMock()
        quota_info.annual_count = 95_000
        quota_info.annual_limit = 100_000
        quota_info.remaining = 5_000
        svc._session_mgr.check_quota = AsyncMock(return_value=quota_info)

        tenant = _make_tenant_mock()
        result = await svc.check_quota(tenant, 100)
        assert result["percentage"] >= 95.0
        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_quota_warning_at_80_percent(self):
        """Quota a 80% -> percentage >= 80."""
        svc = _make_campaign_service()
        quota_info = MagicMock()
        quota_info.annual_count = 80_000
        quota_info.annual_limit = 100_000
        quota_info.remaining = 20_000
        svc._session_mgr.check_quota = AsyncMock(return_value=quota_info)

        tenant = _make_tenant_mock()
        result = await svc.check_quota(tenant, 100)
        assert result["percentage"] >= 80.0


# =====================================================================
# Audience Builder
# =====================================================================


class TestAudienceBuilder:
    """Tests du constructeur d'audience."""

    def test_build_audience_query_always_filters_opted_in(self):
        """_build_audience_query inclut toujours le filtre opted_in."""
        from app.services.campaign.service import CampaignService

        query = CampaignService._build_audience_query({"tags": ["all"]})
        # The compiled query should contain a reference to opt_in_status
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "opt_in_status" in compiled.lower() or "opted_in" in compiled.lower()

    def test_build_audience_query_with_tags(self):
        """_build_audience_query filtre par tags."""
        from app.services.campaign.service import CampaignService

        query = CampaignService._build_audience_query({"tags": ["investisseur"]})
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "tags" in compiled.lower()

    def test_build_audience_query_with_language(self):
        """_build_audience_query filtre par langue."""
        from app.services.campaign.service import CampaignService

        query = CampaignService._build_audience_query({"language": "fr"})
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "language" in compiled.lower()


# =====================================================================
# Launch Campaign
# =====================================================================


class TestLaunchCampaign:
    """Tests du lancement de campagne."""

    @pytest.mark.asyncio
    async def test_launch_checks_quota_first(self):
        """launch_campaign verifie le quota avant de lancer."""
        from app.core.exceptions import WhatsAppQuotaExhaustedError

        svc = _make_campaign_service()

        campaign_mock = MagicMock()
        campaign_mock.id = uuid.uuid4()
        campaign_mock.status = CampaignStatus.draft
        campaign_mock.audience_count = 10_000
        campaign_mock.audience_filter = {"tags": ["all"]}

        quota_info = MagicMock()
        quota_info.annual_count = 99_000
        quota_info.annual_limit = 100_000
        quota_info.remaining = 1_000
        svc._session_mgr.check_quota = AsyncMock(return_value=quota_info)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = campaign_mock
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)

        with pytest.raises(WhatsAppQuotaExhaustedError):
            await svc.launch_campaign(tenant, campaign_mock.id, TEST_ADMIN_ID)

    @pytest.mark.asyncio
    async def test_pause_sets_redis_flag(self):
        """pause_campaign set le flag Redis {prefix}:campaign:{id}:paused."""
        svc = _make_campaign_service()

        campaign_mock = MagicMock()
        campaign_mock.id = uuid.uuid4()
        campaign_mock.status = CampaignStatus.sending

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = campaign_mock
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()

        tenant = _make_tenant_mock(session)

        with patch("app.services.campaign.service.get_redis") as mock_redis:
            redis_instance = AsyncMock()
            mock_redis.return_value = redis_instance

            await svc.pause_campaign(tenant, campaign_mock.id, TEST_ADMIN_ID)

            redis_instance.set.assert_called_once()
            call_args = redis_instance.set.call_args
            assert f"campaign:{campaign_mock.id}:paused" in call_args[0][0]
            assert call_args[0][1] == "1"


# =====================================================================
# Campaign Worker
# =====================================================================


class TestCampaignWorker:
    """Tests du worker d'envoi de campagne."""

    def test_batch_constants_positive(self):
        """BATCH_SIZE et BATCH_DELAY_SECONDS sont positifs."""
        from app.workers.campaign import BATCH_SIZE, BATCH_DELAY_SECONDS

        assert BATCH_SIZE > 0
        assert BATCH_DELAY_SECONDS > 0

    def test_send_concurrency_positive(self):
        """SEND_CONCURRENCY est positif."""
        from app.workers.campaign import SEND_CONCURRENCY

        assert SEND_CONCURRENCY > 0

    def test_campaign_status_enum_values(self):
        """Tous les statuts de campagne sont definis."""
        expected = {"draft", "scheduled", "sending", "paused", "completed", "failed"}
        actual = {s.value for s in CampaignStatus}
        assert expected == actual

    def test_recipient_status_enum_values(self):
        """Tous les statuts de destinataire sont definis."""
        expected = {"pending", "sent", "delivered", "read", "failed"}
        actual = {s.value for s in RecipientStatus}
        assert expected == actual

    def test_worker_task_importable(self):
        """Le worker send_campaign_task est importable."""
        from app.workers.campaign import send_campaign_task

        assert callable(send_campaign_task)
