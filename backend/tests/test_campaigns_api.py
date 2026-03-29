"""Tests for the campaigns REST API (Wave 17).

Covers: imports, route registration, endpoint contracts, service methods.
No database required — uses pure logic tests.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestCampaignsAPIImports:
    """Verify the campaigns API module is importable."""

    def test_router_import(self):
        from app.api.v1.campaigns import router

        assert router is not None

    def test_router_prefix(self):
        from app.api.v1.campaigns import router

        assert router.prefix == "/campaigns"

    def test_router_tags(self):
        from app.api.v1.campaigns import router

        assert "campaigns" in router.tags

    def test_schema_imports(self):
        from app.schemas.campaign import (
            AudiencePreview,
            CampaignCreate,
            CampaignList,
            CampaignRead,
            CampaignSchedule,
            CampaignStats,
            CampaignUpdate,
            RecipientList,
            RecipientRead,
        )

        assert CampaignCreate is not None
        assert CampaignRead is not None
        assert CampaignList is not None
        assert CampaignUpdate is not None
        assert CampaignSchedule is not None
        assert CampaignStats is not None
        assert AudiencePreview is not None
        assert RecipientRead is not None
        assert RecipientList is not None

    def test_service_import(self):
        from app.services.campaign import get_campaign_service

        assert callable(get_campaign_service)

    def test_enum_imports(self):
        from app.models.enums import CampaignStatus, RecipientStatus

        assert CampaignStatus.draft is not None
        assert RecipientStatus.pending is not None


# ---------------------------------------------------------------------------
# 2. Route registration
# ---------------------------------------------------------------------------


class TestCampaignsRoutes:
    """Verify all routes are registered on the router.

    Note: FastAPI router.routes includes the prefix in the path,
    so paths are like /campaigns, /campaigns/quota, etc.
    """

    def _get_route_paths(self):
        from app.api.v1.campaigns import router

        return [route.path for route in router.routes]

    def test_list_route(self):
        paths = self._get_route_paths()
        assert "/campaigns" in paths

    def test_create_route(self):
        paths = self._get_route_paths()
        assert "/campaigns" in paths

    def test_quota_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/quota" in paths

    def test_detail_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}" in paths

    def test_update_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}" in paths

    def test_schedule_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/schedule" in paths

    def test_launch_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/launch" in paths

    def test_pause_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/pause" in paths

    def test_resume_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/resume" in paths

    def test_stats_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/stats" in paths

    def test_recipients_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/recipients" in paths

    def test_preview_route(self):
        paths = self._get_route_paths()
        assert "/campaigns/{campaign_id}/preview" in paths

    def test_total_route_count(self):
        from app.api.v1.campaigns import router

        paths = [route.path for route in router.routes]
        assert len(paths) >= 10

    def test_quota_before_campaign_id(self):
        """Quota route must be before {campaign_id} to avoid UUID parsing."""
        from app.api.v1.campaigns import router

        paths = [route.path for route in router.routes]
        quota_idx = paths.index("/campaigns/quota")
        detail_idx = paths.index("/campaigns/{campaign_id}")
        assert quota_idx < detail_idx


# ---------------------------------------------------------------------------
# 3. Route methods
# ---------------------------------------------------------------------------


class TestCampaignsRouteMethods:
    """Verify HTTP methods are correct for each route."""

    def _get_routes(self):
        from app.api.v1.campaigns import router

        result: dict[str, set[str]] = {}
        for route in router.routes:
            if hasattr(route, "methods"):
                result.setdefault(route.path, set()).update(route.methods)
        return result

    def test_list_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/campaigns"]

    def test_quota_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/campaigns/quota"]

    def test_detail_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/campaigns/{campaign_id}"]

    def test_schedule_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/campaigns/{campaign_id}/schedule"]

    def test_launch_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/campaigns/{campaign_id}/launch"]

    def test_pause_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/campaigns/{campaign_id}/pause"]

    def test_resume_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/campaigns/{campaign_id}/resume"]

    def test_stats_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/campaigns/{campaign_id}/stats"]

    def test_recipients_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/campaigns/{campaign_id}/recipients"]

    def test_preview_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/campaigns/{campaign_id}/preview"]


# ---------------------------------------------------------------------------
# 4. Main app registration
# ---------------------------------------------------------------------------


class TestMainAppRegistration:
    """Verify the campaigns router is registered in main.py."""

    def test_campaigns_router_in_app(self):
        from app.main import app

        route_paths = [route.path for route in app.routes]
        assert any("/campaigns" in p for p in route_paths)


# ---------------------------------------------------------------------------
# 5. Service method contracts
# ---------------------------------------------------------------------------


class TestCampaignServiceMethods:
    """Verify CampaignService has all methods the API depends on."""

    def test_create_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "create_campaign")
        assert callable(getattr(CampaignService, "create_campaign"))

    def test_update_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "update_campaign")
        assert callable(getattr(CampaignService, "update_campaign"))

    def test_get_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "get_campaign")
        assert callable(getattr(CampaignService, "get_campaign"))

    def test_list_campaigns(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "list_campaigns")
        assert callable(getattr(CampaignService, "list_campaigns"))

    def test_launch_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "launch_campaign")
        assert callable(getattr(CampaignService, "launch_campaign"))

    def test_pause_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "pause_campaign")
        assert callable(getattr(CampaignService, "pause_campaign"))

    def test_resume_campaign(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "resume_campaign")
        assert callable(getattr(CampaignService, "resume_campaign"))

    def test_check_quota(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "check_quota")
        assert callable(getattr(CampaignService, "check_quota"))

    def test_get_campaign_stats(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "get_campaign_stats")
        assert callable(getattr(CampaignService, "get_campaign_stats"))

    def test_get_recipients(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "get_recipients")
        assert callable(getattr(CampaignService, "get_recipients"))

    def test_preview_audience(self):
        from app.services.campaign import CampaignService

        assert hasattr(CampaignService, "preview_audience")
        assert callable(getattr(CampaignService, "preview_audience"))
