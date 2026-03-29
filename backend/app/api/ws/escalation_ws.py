"""WebSocket endpoint for real-time escalation notifications.

Architecture:
- Back-office client connects: ws://host/ws/escalations/{slug}?token=<jwt>
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
import json
from datetime import UTC, datetime

import structlog
from fastapi import Query, WebSocket, WebSocketDisconnect

from app.core.exceptions import (
    AuthenticationError,
    TenantInactiveError,
    TenantNotFoundError,
)
from app.core.redis import get_redis
from app.core.tenant import TenantContext, TenantResolver
from app.models.enums import AdminRole
from app.schemas.auth import AdminTokenPayload
from app.services.auth.jwt import JWTManager

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


_WS_ALLOWED_ROLES: frozenset[str] = frozenset({
    AdminRole.supervisor.value,
    AdminRole.admin_tenant.value,
    AdminRole.super_admin.value,
})


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

    async def connect(self, websocket: WebSocket, slug: str) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: The WebSocket to accept.
            slug: Tenant slug.
        """
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
    tenant_slug: str,
    token: str = Query(...),
) -> None:
    """WebSocket endpoint for real-time escalation notifications.

    URL: ws://host/ws/escalations/{tenant_slug}?token=<jwt>

    The client receives events whenever an escalation is created, assigned,
    or resolved for this tenant. The client may send "ping" to receive a
    "pong" keepalive response.

    Args:
        websocket: FastAPI WebSocket connection.
        tenant_slug: Tenant slug from URL path.
        token: JWT access token from query parameter.
    """
    # --- Authenticate ---
    try:
        admin = _authenticate_token(token)
    except (AuthenticationError, Exception):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    if admin.role not in _WS_ALLOWED_ROLES:
        await websocket.close(code=4003, reason="Insufficient permissions")
        return

    # --- Resolve tenant ---
    try:
        tenant: TenantContext = await TenantResolver.from_slug(tenant_slug)
    except (TenantNotFoundError, TenantInactiveError):
        await websocket.close(code=4004, reason="Invalid or inactive tenant")
        return

    # --- Accept connection ---
    await ws_manager.connect(websocket, tenant_slug)
    logger.info(
        "ws_escalation_connected",
        tenant=tenant_slug,
        admin_id=admin.sub,
        admin_role=admin.role,
    )

    # --- Set up Redis pub/sub ---
    redis = get_redis()
    pubsub = redis.pubsub()
    channel_pattern = f"{tenant_slug}:escalations:*"
    await pubsub.psubscribe(channel_pattern)

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

            await ws_manager.broadcast(tenant_slug, event_name, data)

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

    try:
        done, pending = await asyncio.wait(
            [redis_task, client_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        # Cleanup
        await pubsub.punsubscribe(channel_pattern)
        await pubsub.aclose()
        await ws_manager.disconnect(websocket, tenant_slug)
        logger.info(
            "ws_escalation_disconnected",
            tenant=tenant_slug,
            admin_id=admin.sub,
        )
