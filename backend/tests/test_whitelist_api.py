"""Tests for the internal whitelist REST API (Wave 17).

Covers: imports, route registration, endpoint contracts.
No database required — uses pure logic tests.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestWhitelistAPIImports:
    """Verify the whitelist API module is importable."""

    def test_router_import(self):
        from app.api.v1.whitelist import router

        assert router is not None

    def test_router_prefix(self):
        from app.api.v1.whitelist import router

        assert router.prefix == "/whitelist"

    def test_router_tags(self):
        from app.api.v1.whitelist import router

        assert "whitelist" in router.tags

    def test_schema_imports(self):
        from app.schemas.whitelist import (
            InternalWhitelistCreate,
            InternalWhitelistList,
            InternalWhitelistResponse,
            InternalWhitelistUpdate,
            WhitelistCheckResponse,
        )

        assert InternalWhitelistCreate is not None
        assert InternalWhitelistList is not None
        assert InternalWhitelistResponse is not None
        assert InternalWhitelistUpdate is not None
        assert WhitelistCheckResponse is not None

    def test_model_import(self):
        from app.models.whitelist import InternalWhitelist

        assert InternalWhitelist is not None


# ---------------------------------------------------------------------------
# 2. Route registration
# ---------------------------------------------------------------------------


class TestWhitelistRoutes:
    """Verify all 5 routes are registered on the router.

    Note: FastAPI router.routes includes the prefix in the path,
    so paths are like /whitelist, /whitelist/check, etc.
    """

    def _get_route_paths(self):
        from app.api.v1.whitelist import router

        return [route.path for route in router.routes]

    def test_list_route(self):
        paths = self._get_route_paths()
        assert "/whitelist" in paths

    def test_check_route(self):
        paths = self._get_route_paths()
        assert "/whitelist/check" in paths

    def test_create_route(self):
        paths = self._get_route_paths()
        assert "/whitelist" in paths

    def test_update_route(self):
        paths = self._get_route_paths()
        assert "/whitelist/{entry_id}" in paths

    def test_delete_route(self):
        paths = self._get_route_paths()
        assert "/whitelist/{entry_id}" in paths

    def test_total_route_count(self):
        from app.api.v1.whitelist import router

        paths = [route.path for route in router.routes]
        assert len(paths) >= 5

    def test_check_before_entry_id(self):
        """Check route must be before {entry_id} to avoid UUID parsing."""
        from app.api.v1.whitelist import router

        paths = [route.path for route in router.routes]
        check_idx = paths.index("/whitelist/check")
        entry_idx = paths.index("/whitelist/{entry_id}")
        assert check_idx < entry_idx


# ---------------------------------------------------------------------------
# 3. Route methods
# ---------------------------------------------------------------------------


class TestWhitelistRouteMethods:
    """Verify HTTP methods are correct for each route."""

    def _get_routes(self):
        from app.api.v1.whitelist import router

        result: dict[str, set[str]] = {}
        for route in router.routes:
            if hasattr(route, "methods"):
                result.setdefault(route.path, set()).update(route.methods)
        return result

    def test_list_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/whitelist"]

    def test_check_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/whitelist/check"]

    def test_update_is_patch(self):
        routes = self._get_routes()
        assert "PATCH" in routes["/whitelist/{entry_id}"]

    def test_delete_is_delete(self):
        routes = self._get_routes()
        assert "DELETE" in routes["/whitelist/{entry_id}"]


# ---------------------------------------------------------------------------
# 4. Main app registration
# ---------------------------------------------------------------------------


class TestMainAppRegistration:
    """Verify the whitelist router is registered in main.py."""

    def test_whitelist_router_in_app(self):
        from app.main import app

        route_paths = [route.path for route in app.routes]
        assert any("/whitelist" in p for p in route_paths)
