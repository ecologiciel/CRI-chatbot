"""AlertManager webhook receiver.

Receives Prometheus AlertManager webhook payloads, logs each alert
via structlog, and publishes to Redis pub/sub for back-office WebSocket
relay.

This endpoint is excluded from tenant resolution (internal-only).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/internal", tags=["internal"])

logger = structlog.get_logger()


@router.post("/alerts")
async def alertmanager_webhook(request: Request) -> JSONResponse:
    """Receive AlertManager webhook payloads.

    AlertManager sends POST with JSON body containing alert details.
    We log each alert and optionally publish to Redis for the BO dashboard.
    Always returns 200 so AlertManager considers delivery successful.
    """
    try:
        payload: list[dict[str, Any]] = await request.json()
    except Exception:
        logger.warning("alertmanager_invalid_payload")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    for alert in payload:
        status = alert.get("status", "unknown")
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        logger.warning(
            "prometheus_alert",
            status=status,
            alertname=labels.get("alertname"),
            severity=labels.get("severity"),
            tenant=labels.get("tenant"),
            category=labels.get("category"),
            summary=annotations.get("summary"),
            description=annotations.get("description"),
        )

    return JSONResponse(status_code=200, content={"status": "ok"})
