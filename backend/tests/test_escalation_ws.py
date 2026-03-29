"""Tests for the escalation WebSocket module (Wave 16A).

Covers: imports, manager logic, authentication helpers, broadcast format.
No database or Redis required — uses mocks and pure logic tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestWSImports:
    """Verify the WebSocket module is importable."""

    def test_module_import(self):
        from app.api.ws import escalation_ws

        assert escalation_ws is not None

    def test_manager_import(self):
        from app.api.ws.escalation_ws import EscalationWSManager, ws_manager

        assert isinstance(ws_manager, EscalationWSManager)

    def test_endpoint_import(self):
        from app.api.ws.escalation_ws import escalation_ws_endpoint

        assert callable(escalation_ws_endpoint)

    def test_authenticate_helper_import(self):
        from app.api.ws.escalation_ws import _authenticate_token

        assert callable(_authenticate_token)


# ---------------------------------------------------------------------------
# 2. Manager connection tracking
# ---------------------------------------------------------------------------


class TestWSManagerConnections:
    """Test EscalationWSManager connection management."""

    def _make_manager(self):
        from app.api.ws.escalation_ws import EscalationWSManager

        return EscalationWSManager()

    @pytest.mark.asyncio
    async def test_connect_adds_to_set(self):
        mgr = self._make_manager()
        ws = AsyncMock()
        await mgr.connect(ws, "rabat")

        assert "rabat" in mgr._connections
        assert ws in mgr._connections["rabat"]
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self):
        mgr = self._make_manager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "rabat")
        await mgr.connect(ws2, "rabat")

        assert len(mgr._connections["rabat"]) == 2

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_set(self):
        mgr = self._make_manager()
        ws = AsyncMock()
        await mgr.connect(ws, "rabat")
        await mgr.disconnect(ws, "rabat")

        assert "rabat" not in mgr._connections

    @pytest.mark.asyncio
    async def test_disconnect_keeps_other_connections(self):
        mgr = self._make_manager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "rabat")
        await mgr.connect(ws2, "rabat")
        await mgr.disconnect(ws1, "rabat")

        assert ws2 in mgr._connections["rabat"]
        assert ws1 not in mgr._connections["rabat"]

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_slug_no_error(self):
        mgr = self._make_manager()
        ws = AsyncMock()
        # Should not raise
        await mgr.disconnect(ws, "nonexistent")


# ---------------------------------------------------------------------------
# 3. Broadcast
# ---------------------------------------------------------------------------


class TestWSBroadcast:
    """Test broadcast message format and delivery."""

    def _make_manager(self):
        from app.api.ws.escalation_ws import EscalationWSManager

        return EscalationWSManager()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = self._make_manager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "rabat")
        await mgr.connect(ws2, "rabat")

        await mgr.broadcast("rabat", "new", {"id": "test-123"})

        assert ws1.send_text.await_count == 1
        assert ws2.send_text.await_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_message_format(self):
        mgr = self._make_manager()
        ws = AsyncMock()
        await mgr.connect(ws, "rabat")

        await mgr.broadcast("rabat", "new_escalation", {"id": "abc"})

        sent = ws.send_text.call_args[0][0]
        parsed = json.loads(sent)

        assert "event" in parsed
        assert parsed["event"] == "new_escalation"
        assert "data" in parsed
        assert parsed["data"]["id"] == "abc"
        assert "timestamp" in parsed

    @pytest.mark.asyncio
    async def test_broadcast_no_connections_no_error(self):
        mgr = self._make_manager()
        # Should not raise
        await mgr.broadcast("nonexistent", "new", {"id": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self):
        mgr = self._make_manager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = Exception("Connection closed")

        await mgr.connect(ws_alive, "rabat")
        await mgr.connect(ws_dead, "rabat")

        await mgr.broadcast("rabat", "new", {"id": "test"})

        # Dead connection should be removed
        assert ws_dead not in mgr._connections["rabat"]
        assert ws_alive in mgr._connections["rabat"]


# ---------------------------------------------------------------------------
# 4. Authentication
# ---------------------------------------------------------------------------


class TestWSAuthentication:
    """Test WebSocket JWT authentication helper."""

    def test_valid_access_token(self):
        from app.api.ws.escalation_ws import _authenticate_token

        mock_payload = {
            "sub": str(uuid.uuid4()),
            "role": "supervisor",
            "tenant_id": str(uuid.uuid4()),
            "type": "access",
            "iat": 1000,
            "exp": 9999999999,
            "jti": str(uuid.uuid4()),
        }

        with patch(
            "app.api.ws.escalation_ws.JWTManager.verify_token",
            return_value=mock_payload,
        ):
            result = _authenticate_token("valid-token")

        assert result.sub == mock_payload["sub"]
        assert result.role == "supervisor"

    def test_invalid_token_raises(self):
        from app.api.ws.escalation_ws import _authenticate_token
        from app.core.exceptions import AuthenticationError

        with patch(
            "app.api.ws.escalation_ws.JWTManager.verify_token",
            side_effect=AuthenticationError("bad token"),
        ):
            with pytest.raises(AuthenticationError):
                _authenticate_token("bad-token")

    def test_refresh_token_rejected(self):
        from app.api.ws.escalation_ws import _authenticate_token
        from app.core.exceptions import AuthenticationError

        mock_payload = {
            "sub": str(uuid.uuid4()),
            "type": "refresh",  # Not access!
            "iat": 1000,
            "exp": 9999999999,
            "jti": str(uuid.uuid4()),
        }

        with patch(
            "app.api.ws.escalation_ws.JWTManager.verify_token",
            return_value=mock_payload,
        ):
            with pytest.raises(AuthenticationError, match="Invalid token type"):
                _authenticate_token("refresh-token")


# ---------------------------------------------------------------------------
# 5. Allowed roles
# ---------------------------------------------------------------------------


class TestWSAllowedRoles:
    """Verify the WS allowed roles set."""

    def test_supervisor_allowed(self):
        from app.api.ws.escalation_ws import _WS_ALLOWED_ROLES

        assert "supervisor" in _WS_ALLOWED_ROLES

    def test_admin_tenant_allowed(self):
        from app.api.ws.escalation_ws import _WS_ALLOWED_ROLES

        assert "admin_tenant" in _WS_ALLOWED_ROLES

    def test_super_admin_allowed(self):
        from app.api.ws.escalation_ws import _WS_ALLOWED_ROLES

        assert "super_admin" in _WS_ALLOWED_ROLES

    def test_viewer_not_allowed(self):
        from app.api.ws.escalation_ws import _WS_ALLOWED_ROLES

        assert "viewer" not in _WS_ALLOWED_ROLES


import uuid  # noqa: E402 — needed by test fixtures above
