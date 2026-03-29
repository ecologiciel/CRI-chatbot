"""Tests for the escalation REST API (Wave 16A).

Covers: imports, route registration, endpoint contracts.
No database required — uses mocks and pure logic tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestEscalationAPIImports:
    """Verify the escalation API module is importable."""

    def test_router_import(self):
        from app.api.v1.escalation import router

        assert router is not None

    def test_router_prefix(self):
        from app.api.v1.escalation import router

        assert router.prefix == "/escalations"

    def test_router_tags(self):
        from app.api.v1.escalation import router

        assert "escalations" in router.tags

    def test_exception_import(self):
        from app.core.exceptions import EscalationConflictError

        assert EscalationConflictError is not None


# ---------------------------------------------------------------------------
# 2. Route registration
# ---------------------------------------------------------------------------


class TestEscalationRoutes:
    """Verify all 7 routes are registered on the router.

    Note: FastAPI router.routes includes the prefix in the path,
    so paths are like /escalations, /escalations/stats, etc.
    """

    def _get_route_paths(self):
        from app.api.v1.escalation import router

        return [route.path for route in router.routes]

    def test_list_route(self):
        paths = self._get_route_paths()
        assert "/escalations" in paths

    def test_stats_route(self):
        paths = self._get_route_paths()
        assert "/escalations/stats" in paths

    def test_detail_route(self):
        paths = self._get_route_paths()
        assert "/escalations/{escalation_id}" in paths

    def test_assign_route(self):
        paths = self._get_route_paths()
        assert "/escalations/{escalation_id}/assign" in paths

    def test_respond_route(self):
        paths = self._get_route_paths()
        assert "/escalations/{escalation_id}/respond" in paths

    def test_close_route(self):
        paths = self._get_route_paths()
        assert "/escalations/{escalation_id}/close" in paths

    def test_conversation_route(self):
        paths = self._get_route_paths()
        assert "/escalations/{escalation_id}/conversation" in paths

    def test_total_route_count(self):
        from app.api.v1.escalation import router

        paths = [route.path for route in router.routes]
        assert len(paths) >= 7

    def test_stats_before_detail(self):
        """Stats route must be before {escalation_id} to avoid UUID parsing."""
        from app.api.v1.escalation import router

        paths = [route.path for route in router.routes]
        stats_idx = paths.index("/escalations/stats")
        detail_idx = paths.index("/escalations/{escalation_id}")
        assert stats_idx < detail_idx


# ---------------------------------------------------------------------------
# 3. Route methods
# ---------------------------------------------------------------------------


class TestEscalationRouteMethods:
    """Verify HTTP methods are correct for each route."""

    def _get_routes(self):
        from app.api.v1.escalation import router

        return {route.path: route.methods for route in router.routes if hasattr(route, "methods")}

    def test_list_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/escalations"]

    def test_stats_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/escalations/stats"]

    def test_detail_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/escalations/{escalation_id}"]

    def test_assign_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/escalations/{escalation_id}/assign"]

    def test_respond_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/escalations/{escalation_id}/respond"]

    def test_close_is_post(self):
        routes = self._get_routes()
        assert "POST" in routes["/escalations/{escalation_id}/close"]

    def test_conversation_is_get(self):
        routes = self._get_routes()
        assert "GET" in routes["/escalations/{escalation_id}/conversation"]


# ---------------------------------------------------------------------------
# 4. Exception mapping in main.py
# ---------------------------------------------------------------------------


class TestEscalationExceptionMapping:
    """Verify EscalationConflictError is mapped to HTTP 409."""

    def test_conflict_error_mapped(self):
        from app.core.exceptions import EscalationConflictError
        from app.main import _get_status_code

        exc = EscalationConflictError("test conflict")
        assert _get_status_code(exc) == 409


# ---------------------------------------------------------------------------
# 5. Service method contracts
# ---------------------------------------------------------------------------


class TestEscalationServiceNewMethods:
    """Verify new service methods exist with correct signatures."""

    def test_get_by_id_exists(self):
        from app.services.escalation.service import EscalationService

        assert hasattr(EscalationService, "get_escalation_by_id")
        assert callable(getattr(EscalationService, "get_escalation_by_id"))

    def test_get_escalations_exists(self):
        from app.services.escalation.service import EscalationService

        assert hasattr(EscalationService, "get_escalations")
        assert callable(getattr(EscalationService, "get_escalations"))

    def test_get_stats_exists(self):
        from app.services.escalation.service import EscalationService

        assert hasattr(EscalationService, "get_escalation_stats")
        assert callable(getattr(EscalationService, "get_escalation_stats"))

    def test_get_conversation_messages_exists(self):
        from app.services.escalation.service import EscalationService

        assert hasattr(EscalationService, "get_conversation_messages")
        assert callable(getattr(EscalationService, "get_conversation_messages"))


# ---------------------------------------------------------------------------
# 6. Main app registration
# ---------------------------------------------------------------------------


class TestMainAppRegistration:
    """Verify the escalation router and WS endpoint are in main.py."""

    def test_escalation_router_in_app(self):
        from app.main import app

        route_paths = [route.path for route in app.routes]
        # Check that /api/v1/escalations is registered
        assert any("/escalations" in p for p in route_paths)

    def test_ws_route_in_app(self):
        from app.main import app

        route_paths = [route.path for route in app.routes]
        assert any("/ws/escalations" in p for p in route_paths)


# ---------------------------------------------------------------------------
# 7. Middleware exclusions
# ---------------------------------------------------------------------------


class TestMiddlewareExclusions:
    """Verify /ws/ is excluded from tenant and audit middlewares."""

    def test_tenant_middleware_excludes_ws(self):
        from app.core.middleware import TENANT_EXCLUDED_PREFIXES

        assert any(prefix.startswith("/ws") for prefix in TENANT_EXCLUDED_PREFIXES)

    def test_audit_middleware_excludes_ws(self):
        from app.core.audit_middleware import AUDIT_EXCLUDED_PREFIXES

        assert any(prefix.startswith("/ws") for prefix in AUDIT_EXCLUDED_PREFIXES)
