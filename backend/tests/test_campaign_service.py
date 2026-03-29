"""Tests for CampaignService — CRUD, audience, quota, lifecycle, and worker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import CampaignStatus, Language, OptInStatus, RecipientStatus


# ---------------------------------------------------------------------------
# Import tests (sync)
# ---------------------------------------------------------------------------


class TestCampaignImports:
    """Verify that campaign service and worker modules are importable."""

    def test_service_import(self):
        from app.services.campaign.service import CampaignService

        assert CampaignService is not None

    def test_singleton_factory_import(self):
        from app.services.campaign.service import get_campaign_service

        assert callable(get_campaign_service)

    def test_package_reexport(self):
        from app.services.campaign import CampaignService, get_campaign_service

        assert CampaignService is not None
        assert callable(get_campaign_service)

    def test_worker_import(self):
        from app.workers.campaign import send_campaign_task

        assert callable(send_campaign_task)

    def test_worker_constants(self):
        from app.workers.campaign import BATCH_DELAY_SECONDS, BATCH_SIZE, SEND_CONCURRENCY

        assert BATCH_SIZE > 0
        assert BATCH_DELAY_SECONDS > 0
        assert SEND_CONCURRENCY > 0


# ---------------------------------------------------------------------------
# Variable resolution (sync — pure logic)
# ---------------------------------------------------------------------------


class TestVariableResolution:
    """Test CampaignService.resolve_variables (static method)."""

    def _make_contact(self, **overrides):
        """Build a mock Contact with sensible defaults."""
        contact = MagicMock()
        contact.name = overrides.get("name", "Ahmed")
        contact.phone = overrides.get("phone", "+212600000001")
        contact.language = overrides.get("language", Language.fr)
        contact.tags = overrides.get("tags", [])
        contact.opt_in_status = overrides.get("opt_in_status", OptInStatus.opted_in)
        return contact

    def test_contact_name(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact(name="Ahmed")
        result = CampaignService.resolve_variables({"1": "contact.name"}, contact)

        assert len(result) == 1
        assert result[0]["type"] == "body"
        assert result[0]["parameters"] == [{"type": "text", "text": "Ahmed"}]

    def test_contact_phone(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact(phone="+212612345678")
        result = CampaignService.resolve_variables({"1": "contact.phone"}, contact)

        assert result[0]["parameters"] == [{"type": "text", "text": "+212612345678"}]

    def test_custom_text(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact()
        result = CampaignService.resolve_variables({"1": "custom:Bienvenue"}, contact)

        assert result[0]["parameters"] == [{"type": "text", "text": "Bienvenue"}]

    def test_null_name_fallback(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact(name=None)
        result = CampaignService.resolve_variables({"1": "contact.name"}, contact)

        assert result[0]["parameters"] == [{"type": "text", "text": "Investisseur"}]

    def test_empty_mapping(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact()
        result = CampaignService.resolve_variables({}, contact)

        assert result == []

    def test_multiple_variables_ordered(self):
        from app.services.campaign.service import CampaignService

        contact = self._make_contact(name="Fatima")
        result = CampaignService.resolve_variables(
            {"2": "custom:Votre dossier", "1": "contact.name"},
            contact,
        )

        params = result[0]["parameters"]
        assert params[0]["text"] == "Fatima"
        assert params[1]["text"] == "Votre dossier"


# ---------------------------------------------------------------------------
# Quota check (async, mocked Redis)
# ---------------------------------------------------------------------------


class TestQuotaCheck:
    """Test CampaignService.check_quota."""

    @pytest.fixture()
    def _mock_deps(self):
        """Provide mocked dependencies for CampaignService."""
        sender = MagicMock()
        audit = AsyncMock()
        session_mgr = AsyncMock()
        return sender, audit, session_mgr

    def _make_quota_info(self, annual_count: int, annual_limit: int = 100_000):
        """Build a mock QuotaInfo dataclass."""
        remaining = max(0, annual_limit - annual_count)
        qi = MagicMock()
        qi.annual_count = annual_count
        qi.annual_limit = annual_limit
        qi.remaining = remaining
        qi.is_exhausted = remaining == 0
        qi.is_warning = annual_count >= int(annual_limit * 0.80)
        return qi

    @pytest.mark.asyncio()
    async def test_quota_allowed(self, _mock_deps):
        from app.services.campaign.service import CampaignService

        sender, audit, session_mgr = _mock_deps
        session_mgr.check_quota.return_value = self._make_quota_info(50_000)

        svc = CampaignService(sender=sender, audit=audit, session_mgr=session_mgr)
        tenant = MagicMock()
        tenant.slug = "rabat"
        tenant.redis_prefix = "rabat"

        result = await svc.check_quota(tenant, 1_000)

        assert result["allowed"] is True
        assert result["used"] == 50_000
        assert result["remaining"] == 50_000
        assert result["limit"] == 100_000
        assert result["percentage"] == 50.0

    @pytest.mark.asyncio()
    async def test_quota_exceeded(self, _mock_deps):
        from app.services.campaign.service import CampaignService

        sender, audit, session_mgr = _mock_deps
        session_mgr.check_quota.return_value = self._make_quota_info(99_500)

        svc = CampaignService(sender=sender, audit=audit, session_mgr=session_mgr)
        tenant = MagicMock()
        tenant.slug = "rabat"
        tenant.redis_prefix = "rabat"

        result = await svc.check_quota(tenant, 1_000)

        assert result["allowed"] is False
        assert result["remaining"] == 500
        assert result["percentage"] == 99.5

    @pytest.mark.asyncio()
    async def test_quota_warning_threshold(self, _mock_deps):
        from app.services.campaign.service import CampaignService

        sender, audit, session_mgr = _mock_deps
        session_mgr.check_quota.return_value = self._make_quota_info(80_000)

        svc = CampaignService(sender=sender, audit=audit, session_mgr=session_mgr)
        tenant = MagicMock()
        tenant.slug = "rabat"
        tenant.redis_prefix = "rabat"

        result = await svc.check_quota(tenant, 100)

        assert result["allowed"] is True
        assert result["percentage"] == 80.0


# ---------------------------------------------------------------------------
# Stats computation (sync)
# ---------------------------------------------------------------------------


class TestCampaignStats:
    """Test CampaignStats computation via get_campaign_stats."""

    @pytest.mark.asyncio()
    async def test_stats_rates(self):
        from app.services.campaign.service import CampaignService

        svc = CampaignService(
            sender=MagicMock(),
            audit=AsyncMock(),
            session_mgr=AsyncMock(),
        )

        # Mock get_campaign to return a campaign with stats
        mock_campaign = MagicMock()
        mock_campaign.stats = {
            "total": 1000,
            "sent": 800,
            "delivered": 600,
            "read": 300,
            "failed": 100,
        }
        with patch.object(svc, "get_campaign", return_value=mock_campaign):
            tenant = MagicMock()
            stats = await svc.get_campaign_stats(tenant, uuid.uuid4())

        assert stats.total == 1000
        assert stats.sent == 800
        assert stats.delivered == 600
        assert stats.read == 300
        assert stats.failed == 100
        assert stats.pending == 100  # 1000 - 800 - 100
        assert stats.delivery_rate == 75.0  # 600/800 * 100
        assert stats.read_rate == 50.0  # 300/600 * 100

    @pytest.mark.asyncio()
    async def test_stats_zero_division_safe(self):
        from app.services.campaign.service import CampaignService

        svc = CampaignService(
            sender=MagicMock(),
            audit=AsyncMock(),
            session_mgr=AsyncMock(),
        )

        mock_campaign = MagicMock()
        mock_campaign.stats = {
            "total": 100,
            "sent": 0,
            "delivered": 0,
            "read": 0,
            "failed": 0,
        }
        with patch.object(svc, "get_campaign", return_value=mock_campaign):
            stats = await svc.get_campaign_stats(MagicMock(), uuid.uuid4())

        assert stats.delivery_rate is None
        assert stats.read_rate is None
        assert stats.pending == 100


# ---------------------------------------------------------------------------
# Campaign lifecycle validations
# ---------------------------------------------------------------------------


class TestCampaignLifecycle:
    """Test status transition validations."""

    def test_campaign_status_values(self):
        """Verify all expected campaign statuses exist."""
        expected = {"draft", "scheduled", "sending", "paused", "completed", "failed"}
        actual = {s.value for s in CampaignStatus}
        assert actual == expected

    def test_recipient_status_values(self):
        """Verify all expected recipient statuses exist."""
        expected = {"pending", "sent", "delivered", "read", "failed"}
        actual = {s.value for s in RecipientStatus}
        assert actual == expected
