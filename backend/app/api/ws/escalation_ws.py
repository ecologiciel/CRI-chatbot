"""WebSocket endpoint for real-time escalation notifications.

Architecture:
- Back-office connects with a tenant UUID and authenticates in the first frame.
- Server subscribes to Redis pub/sub pattern {slug}:escalations:*
- When EscalationService publishes an event, it is forwarded to all
  connected WebSocket clients for that tenant.

Events pushed:
- new         — new escalation created
- assigned    — escalation taken by an admin
- resolved    — escalation closed

Message format: {"event": "new", "data": {...}, "timestamp": "ISO"}

Close codes:
- 4001 — authentication failure (missing/invalid JWT)
- 4003 — authorization failure (insufficient role)
- 4004 — tenant not found or inactive
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    TenantInactiveError,
    TenantNotFoundError,
)
from app.core.rbac import ensure_admin_access
from app.core.redis import get_redis
from app.core.tenant import TenantContext, TenantResolver
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------


def _authenticate_token(token: str) -> AdminTokenPayload:
    """Verify JWT token and return admin payload.

    Args:
        token: Raw JWT string from query parameter.

    Returns:
        AdminTokenPayload with decoded claims.

    Raises:
        AuthenticationError: If token is invalid, expired, or wrong type.
    """
    payload = JWTManager.verify_token(token)  # raises AuthenticationError

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type for WebSocket")

    return AdminTokenPayload(**payload)


_WS_ALLOWED_ROLES: frozenset[str] = frozenset(
    {
        AdminRole.supervisor.value,
        AdminRole.admin_tenant.value,
        AdminRole.super_admin.value,
    }
)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


class EscalationWSManager:
    """Manages active WebSocket connections per tenant slug.

    Thread-safe within a single asyncio event loop (no multi-thread access).
    Each uvicorn worker gets its own manager instance; Redis pub/sub ensures
    every worker receives every event.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, slug: str, *, accepted: bool = False) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: The WebSocket to accept.
            slug: Tenant slug.
        """
        if not accepted:
            await websocket.accept()
        if slug not in self._connections:
            self._connections[slug] = set()
        self._connections[slug].add(websocket)

    async def disconnect(self, websocket: WebSocket, slug: str) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket to remove.
            slug: Tenant slug.
        """
        if slug in self._connections:
            self._connections[slug].discard(websocket)
            if not self._connections[slug]:
                del self._connections[slug]

    async def broadcast(self, slug: str, event: str, data: dict) -> None:
        """Send an event to all connected clients for a tenant.

        Dead connections are cleaned up automatically.

        Args:
            slug: Tenant slug.
            event: Event name (e.g., "new", "assigned", "resolved").
            data: Event payload dict.
        """
        if slug not in self._connections:
            return

        message = json.dumps(
            {
                "event": event,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            default=str,
            ensure_ascii=False,
        )

        dead: list[WebSocket] = []
        for ws in self._connections[slug]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections[slug].discard(ws)


# Module-level singleton
ws_manager = EscalationWSManager()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


async def escalation_ws_endpoint(
    websocket: WebSocket,
    tenant_id: str,
) -> None:
    """WebSocket endpoint for real-time escalation notifications.

    URL: wss://host/ws/escalations/{tenant_id}

    The client receives events whenever an escalation is created, assigned,
    or resolved for this tenant. The client may send "ping" to receive a
    "pong" keepalive response.

    Args:
        websocket: FastAPI WebSocket connection.
        tenant_id: Tenant UUID from URL path.
    """
    # Authentication is sent in the first frame, never in the URL or proxy logs.
    await websocket.accept()
    ip_address = websocket.client.host if websocket.client else None
    if not ip_address:
        await websocket.close(code=4001, reason="Unable to validate session")
        return

    try:
        first_frame = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(first_frame) > 8192:
            raise ValueError("oversized authentication frame")
        auth_frame = json.loads(first_frame)
        if not isinstance(auth_frame, dict) or auth_frame.get("type") != "auth":
            raise ValueError("invalid authentication frame")
        token = auth_frame.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("missing token")
    except (ValueError, TypeError, TimeoutError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await websocket.close(code=4001, reason="Authentication required")
        return

    bound_slug: str | None = None

    async def validate_access() -> tuple[AdminTokenPayload, TenantContext]:
        admin = await AuthService().verify_access_token(token, ip_address=ip_address)
        if admin.role not in _WS_ALLOWED_ROLES:
            raise AuthorizationError("Insufficient permissions")
        tenant = await TenantResolver.from_tenant_id_header(tenant_id)
        if bound_slug is not None and tenant.slug != bound_slug:
            raise AuthorizationError("Tenant routing changed")
        await ensure_admin_access(admin, tenant.id)
        return admin, tenant

    # --- Authenticate, including the current Redis-backed session ---
    try:
        admin, tenant = await validate_access()
    except AuthenticationError:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    except AuthorizationError:
        await websocket.close(code=4003, reason="Insufficient permissions")
        return
    except (TenantNotFoundError, TenantInactiveError):
        await websocket.close(code=4004, reason="Invalid or inactive tenant")
        return
    except Exception:
        logger.warning("ws_escalation_auth_unavailable", tenant_id=tenant_id)
        await websocket.close(code=1011, reason="Session validation unavailable")
        return

    # --- Accept connection ---
    tenant_slug = tenant.slug
    bound_slug = tenant_slug
    await ws_manager.connect(websocket, tenant_slug, accepted=True)
    logger.info(
        "ws_escalation_connected",
        tenant=tenant_slug,
        admin_id=admin.sub,
        admin_role=admin.role,
    )

    # --- Set up Redis pub/sub ---
    try:
        redis = get_redis()
        pubsub = redis.pubsub()
    except Exception:
        await ws_manager.disconnect(websocket, tenant_slug)
        await websocket.close(code=1011, reason="Notifications unavailable")
        return
    channel_pattern = f"{tenant_slug}:escalations:*"
    try:
        await pubsub.psubscribe(channel_pattern)
        await websocket.send_text(json.dumps({"event": "authenticated"}))
    except Exception:
        with contextlib.suppress(Exception):
            await pubsub.aclose()
        await ws_manager.disconnect(websocket, tenant_slug)
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Notifications unavailable")
        return

    async def _listen_redis() -> None:
        """Forward Redis pub/sub messages to the WebSocket client."""
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()

            raw_data = message["data"]
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode()

            # Extract event name from channel: {slug}:escalations:new → "new"
            event_name = channel.rsplit(":", maxsplit=1)[-1]

            try:
                data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                data = {"raw": raw_data}

            # Each connection has its own subscription; broadcasting here
            # would send every event once per connection to every client.
            try:
                await validate_access()
            except Exception:
                await websocket.close(code=4001, reason="Session no longer valid")
                return
            await websocket.send_text(json.dumps({
                "event": event_name,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            }, default=str, ensure_ascii=False))

    async def _watch_access() -> None:
        """Close idle connections after revocation, expiry or tenant changes."""
        while True:
            await asyncio.sleep(30)
            try:
                await validate_access()
            except Exception:
                await websocket.close(code=4001, reason="Session no longer valid")
                return

    async def _listen_client() -> None:
        """Listen for client messages (ping/pong keepalive)."""
        while True:
            try:
                text = await websocket.receive_text()
                if text == "ping":
                    await websocket.send_text(
                        json.dumps({"event": "pong", "timestamp": datetime.now(UTC).isoformat()}),
                    )
            except WebSocketDisconnect:
                break

    # --- Run both listeners concurrently ---
    redis_task = asyncio.create_task(_listen_redis())
    client_task = asyncio.create_task(_listen_client())
    access_task = asyncio.create_task(_watch_access())
    tasks = [redis_task, client_task, access_task]

    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Cleanup
        with contextlib.suppress(Exception):
            await pubsub.punsubscribe(channel_pattern)
        with contextlib.suppress(Exception):
            await pubsub.aclose()
        await ws_manager.disconnect(websocket, tenant_slug)
        with contextlib.suppress(Exception):
            await websocket.close()
        logger.info(
            "ws_escalation_disconnected",
            tenant=tenant_slug,
            admin_id=admin.sub,
        )
